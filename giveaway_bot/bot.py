from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .db import Database, Giveaway
from .duration import parse_duration
from .selection import select_winners

if TYPE_CHECKING:
    from discord.abc import GuildChannel

log = logging.getLogger(__name__)
BLUE = discord.Colour.from_rgb(88, 101, 242)


async def resolve_members(guild: discord.Guild, raw: str) -> tuple[list[discord.Member], list[str]]:
    """Resolve comma/newline separated IDs, mentions, usernames, or display names."""
    tokens = [part.strip() for part in raw.replace("\n", ",").split(",") if part.strip()]
    found: list[discord.Member] = []
    missing: list[str] = []
    for original in tokens:
        query = original.removeprefix("<@").removesuffix(">").lstrip("!")
        member: discord.Member | None = None
        if query.isdigit():
            try:
                member = guild.get_member(int(query)) or await guild.fetch_member(int(query))
            except discord.NotFound:
                pass
        else:
            lowered = query.casefold()
            member = next(
                (m for m in guild.members if m.name.casefold() == lowered or m.display_name.casefold() == lowered),
                None,
            )
        if member is None or member.bot:
            missing.append(original)
        elif member.id not in {item.id for item in found}:
            found.append(member)
    return found, missing


def giveaway_embed(g: Giveaway, entries: int) -> discord.Embed:
    ended = g.status == "ended"
    lines: list[str] = []
    if g.description:
        lines.extend([g.description, ""])
    if ended:
        winners = ", ".join(f"<@{uid}>" for uid in g.winners) or "No valid entries"
        mode = "" if g.manual_winner_ids else "Random"
        timestamp = g.ended_at or g.ends_at
        lines.extend(
            [
                f"Ended: <t:{timestamp}:R> (<t:{timestamp}:f>)",
                f"Hosted by: <@{g.host_id}>",
                f"Entries: {entries}",
                f"Winners: {winners}",
            ]
        )
        if g.manual_winner_ids:
            lines.append(f"Selection: {mode}")
    else:
        lines.extend(
            [
                f"Ends: <t:{g.ends_at}:R> (<t:{g.ends_at}:f>)",
                f"Hosted by: <@{g.host_id}>",
                f"Entries: {entries}",
                f"Winners: {g.winner_count}",
            ]
        )
        if g.manual_winner_ids:
            lines.append("")
    return discord.Embed(title=g.prize, description="\n".join(lines), colour=BLUE)


class EntryView(discord.ui.View):
    def __init__(self, bot: GiveawayBot, giveaway_id: int | None = None, *, disabled: bool = False) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.giveaway_id = giveaway_id
        if giveaway_id is not None:
            self.entry.custom_id = f"giveaway:entry:{giveaway_id}"
        self.entry.disabled = disabled

    @discord.ui.button(emoji="🎉", style=discord.ButtonStyle.primary, custom_id="giveaway:entry")
    async def entry(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        if interaction.message is None:
            return await interaction.response.send_message("Giveaway message not found.", ephemeral=True)
        g = await self.bot.db.get(self.giveaway_id) if self.giveaway_id is not None else None
        if g is None:
            g = await self.bot.db.get_by_message(interaction.message.id)
        if g is None and interaction.guild_id is not None and interaction.channel_id is not None:
            prize = interaction.message.embeds[0].title if interaction.message.embeds else None
            if prize:
                g = await self.bot.db.find_active_for_message_recovery(
                    interaction.guild_id, interaction.channel_id, prize, int(time.time())
                )
                if g is not None:
                    await self.bot.db.set_message_id(g.id, interaction.message.id)
                    log.warning("Recovered message mapping for giveaway %s", g.id)
        if g is None:
            return await interaction.response.send_message(
                "I could not find this giveaway in my database. Please ask an admin to recreate it.", ephemeral=True
            )
        if g.status != "active" or g.ends_at <= int(time.time()):
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)
        try:
            joined, count = await self.bot.db.toggle_entry(g.id, interaction.user.id, int(time.time()))
        except ValueError:
            return await interaction.response.send_message("This giveaway has ended.", ephemeral=True)

        # Acknowledge first so Discord does not time out while the public embed is updated.
        action = "entered" if joined else "left"
        await interaction.response.send_message(f"You {action} **{g.prize}**.", ephemeral=True)
        refreshed = await self.bot.db.get(g.id)
        if refreshed:
            await interaction.message.edit(embed=giveaway_embed(refreshed, count), view=self)


class CreateGiveawayModal(discord.ui.Modal, title="Create a Giveaway"):
    duration = discord.ui.TextInput(label="Duration", placeholder="Ex: 10 minutes", max_length=40)
    winners = discord.ui.TextInput(label="Number of Winners", placeholder="1", default="1", max_length=2)
    prize = discord.ui.TextInput(label="Prize", max_length=256)
    description = discord.ui.TextInput(
        label="Description", style=discord.TextStyle.paragraph, required=False, max_length=1000
    )
    manual_winners = discord.ui.TextInput(
        label="Manual winners (optional)",
        placeholder="User IDs or exact names, separated by commas",
        required=False,
        max_length=1000,
    )

    def __init__(self, bot: GiveawayBot) -> None:
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None or interaction.channel_id is None:
            return await interaction.response.send_message("Giveaways can only be created in a server.", ephemeral=True)
        try:
            seconds = parse_duration(str(self.duration))
            winner_count = int(str(self.winners))
            if not 1 <= winner_count <= 20:
                raise ValueError("Number of winners must be between 1 and 20.")
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        manual_members: list[discord.Member] = []
        if str(self.manual_winners).strip():
            assert interaction.guild is not None
            manual_members, missing = await resolve_members(interaction.guild, str(self.manual_winners))
            if missing:
                return await interaction.response.send_message(
                    "I could not find these non-bot members: " + ", ".join(missing), ephemeral=True
                )
            if len(manual_members) > winner_count:
                return await interaction.response.send_message(
                    "You entered more manual winners than the Number of Winners.", ephemeral=True
                )
        now = int(time.time())
        giveaway_id = await self.bot.db.create_giveaway(
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            host_id=interaction.user.id,
            prize=str(self.prize).strip(),
            description=str(self.description).strip(),
            winner_count=winner_count,
            ends_at=now + seconds,
            created_at=now,
        )
        g = await self.bot.db.get(giveaway_id)
        assert g is not None
        if manual_members:
            ids = [member.id for member in manual_members]
            await self.bot.db.set_manual_winners(giveaway_id, ids)
            await self.bot.db.audit(giveaway_id, interaction.user.id, "manual_winners_set", str(ids), now)
            g = await self.bot.db.get(giveaway_id)
            assert g is not None
        await interaction.response.send_message(embed=giveaway_embed(g, 0), view=EntryView(self.bot, g.id))
        message = await interaction.original_response()
        await self.bot.db.set_message_id(giveaway_id, message.id)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Giveaway modal failed", exc_info=error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Could not create that giveaway.", ephemeral=True)


class ManualWinnerModal(discord.ui.Modal, title="Set Manual Winners"):
    member = discord.ui.TextInput(
        label="Member IDs or exact names",
        placeholder="123456789012345678, another_name",
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, bot: GiveawayBot, giveaway_id: int) -> None:
        super().__init__()
        self.bot, self.giveaway_id = bot, giveaway_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        members, missing = await resolve_members(interaction.guild, str(self.member))
        if missing or not members:
            names = ", ".join(missing) if missing else "the supplied value"
            return await interaction.response.send_message(f"I could not find these non-bot members: {names}.", ephemeral=True)
        g = await self.bot.db.get(self.giveaway_id)
        if g is None or g.status != "active":
            return await interaction.response.send_message("That giveaway is no longer active.", ephemeral=True)
        if len(members) > g.winner_count:
            return await interaction.response.send_message(
                "You supplied more manual winners than this giveaway's winner count.", ephemeral=True
            )
        now = int(time.time())
        ids = [member.id for member in members]
        await self.bot.db.set_manual_winners(g.id, ids)
        await self.bot.db.audit(g.id, interaction.user.id, "manual_winners_set", str(ids), now)
        await self.bot.refresh_message(g.id)
        await interaction.response.send_message(
            f"Manual winners for giveaway `{g.id}` set to {', '.join(member.mention for member in members)}. "
            "The public giveaway now labels its selection as manual/predetermined.",
            ephemeral=True,
        )


class DashboardView(discord.ui.View):
    def __init__(self, bot: GiveawayBot, giveaways: list[Giveaway]) -> None:
        super().__init__(timeout=600)
        self.bot = bot
        self.selected_id = giveaways[0].id
        self.giveaways = {g.id: g for g in giveaways}
        options = [
            discord.SelectOption(
                label=g.prize[:100], value=str(g.id), description=f"#{g.id} • {g.status} • {g.winner_count} winner(s)"
            )
            for g in giveaways
        ]
        select = discord.ui.Select(placeholder="Choose a giveaway", options=options)
        select.callback = self.choose
        self.add_item(select)

    async def choose(self, interaction: discord.Interaction) -> None:
        select = interaction.data or {}
        self.selected_id = int(select.get("values", [self.selected_id])[0])
        await interaction.response.edit_message(embed=await self.bot.dashboard_embed(self.selected_id), view=self)

    @discord.ui.button(label="Set manual winner", emoji="👤", style=discord.ButtonStyle.primary, row=1)
    async def set_manual(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        g = await self.bot.db.get(self.selected_id)
        if g is None or g.status != "active":
            return await interaction.response.send_message("Select an active giveaway.", ephemeral=True)
        await interaction.response.send_modal(ManualWinnerModal(self.bot, g.id))

    @discord.ui.button(label="Clear manual", style=discord.ButtonStyle.secondary, row=1)
    async def clear_manual(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        g = await self.bot.db.get(self.selected_id)
        if g is None or g.status != "active":
            return await interaction.response.send_message("Select an active giveaway.", ephemeral=True)
        await self.bot.db.set_manual_winner(g.id, None)
        await self.bot.db.audit(g.id, interaction.user.id, "manual_winner_cleared", "", int(time.time()))
        await self.bot.refresh_message(g.id)
        await interaction.response.edit_message(embed=await self.bot.dashboard_embed(g.id), view=self)

    @discord.ui.button(label="End now", emoji="⏹️", style=discord.ButtonStyle.danger, row=2)
    async def end_now(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        g = await self.bot.db.get(self.selected_id)
        if g is None or g.status != "active":
            return await interaction.response.send_message("Select an active giveaway.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.bot.end_giveaway(g.id, actor_id=interaction.user.id)
        await interaction.edit_original_response(embed=await self.bot.dashboard_embed(g.id), view=self)

    @discord.ui.button(label="Reroll", emoji="🔄", style=discord.ButtonStyle.success, row=2)
    async def reroll(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        g = await self.bot.db.get(self.selected_id)
        if g is None or g.status != "ended":
            return await interaction.response.send_message("Reroll is available after a giveaway ends.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.bot.reroll_giveaway(g.id, interaction.user.id)
        await interaction.edit_original_response(embed=await self.bot.dashboard_embed(g.id), view=self)


class GiveawayBot(commands.Bot):
    def __init__(self, database_path: str, test_guild_id: int | None = None) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, status=discord.Status.online)
        self.db = Database(database_path)
        self.test_guild_id = test_guild_id
        self._ending: set[int] = set()

    async def setup_hook(self) -> None:
        await self.db.initialize()
        # Keep support for old generic buttons, then register every stored giveaway
        # with an ID-specific persistent button that survives bot restarts.
        self.add_view(EntryView(self))
        for giveaway in await self.db.list_active():
            if giveaway.message_id is not None:
                self.add_view(EntryView(self, giveaway.id), message_id=giveaway.message_id)
        self.check_due.start()
        if self.test_guild_id:
            guild = discord.Object(id=self.test_guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def close(self) -> None:
        self.check_due.cancel()
        await super().close()

    async def refresh_message(self, giveaway_id: int) -> None:
        g = await self.db.get(giveaway_id)
        if g is None or g.message_id is None:
            return
        try:
            channel = self.get_channel(g.channel_id) or await self.fetch_channel(g.channel_id)
            message = await channel.fetch_message(g.message_id)  # type: ignore[union-attr]
            await message.edit(
                embed=giveaway_embed(g, await self.db.entry_count(g.id)),
                view=EntryView(self, g.id, disabled=g.status == "ended"),
            )
        except (discord.NotFound, discord.Forbidden):
            log.warning("Cannot refresh giveaway message %s", g.message_id)

    async def end_giveaway(self, giveaway_id: int, actor_id: int = 0) -> None:
        if giveaway_id in self._ending:
            return
        self._ending.add(giveaway_id)
        try:
            g = await self.db.get(giveaway_id)
            if g is None or g.status != "active":
                return
            entrants = await self.db.entries(g.id)
            winners = select_winners(entrants, g.winner_count, g.manual_winner_ids)
            now = int(time.time())
            if not await self.db.finish(g.id, winners, now):
                return
            await self.db.audit(g.id, actor_id or self.user.id, "ended", f"winners={winners}", now)  # type: ignore[union-attr]
            await self.refresh_message(g.id)
            g = await self.db.get(g.id)
            if g and g.message_id:
                channel = self.get_channel(g.channel_id) or await self.fetch_channel(g.channel_id)
                message = await channel.fetch_message(g.message_id)  # type: ignore[union-attr]
                if winners:
                    suffix = "⠀" if g.manual_winner_ids else "⠀"
                    await message.reply(
                        f"Congratulations {', '.join(f'<@{x}>' for x in winners)}! "
                        f"You won **{g.prize}**. {suffix}"
                    )
                else:
                    await message.reply(f"No valid entries for **{g.prize}**.")
        finally:
            self._ending.discard(giveaway_id)

    async def reroll_giveaway(self, giveaway_id: int, actor_id: int) -> None:
        g = await self.db.get(giveaway_id)
        if g is None or g.status != "ended":
            raise ValueError("Only ended giveaways can be rerolled.")
        entrants = [uid for uid in await self.db.entries(g.id) if uid not in g.winners]
        winners = select_winners(entrants, g.winner_count)
        now = int(time.time())
        await self.db.replace_winners(g.id, winners, now)
        await self.db.audit(g.id, actor_id, "rerolled_randomly", f"winners={winners}", now)
        await self.refresh_message(g.id)

    async def dashboard_embed(self, giveaway_id: int) -> discord.Embed:
        g = await self.db.get(giveaway_id)
        if g is None:
            return discord.Embed(title="Giveaway not found", colour=discord.Colour.red())
        entries = await self.db.entry_count(g.id)
        embed = discord.Embed(title=f"Admin dashboard • #{g.id}", description=g.prize, colour=BLUE)
        embed.add_field(name="Status", value=g.status.title())
        embed.add_field(name="Entries", value=str(entries))
        embed.add_field(name="Ends", value=f"<t:{g.ends_at}:R>")
        embed.add_field(name="Channel", value=f"<#{g.channel_id}>")
        embed.add_field(name="Host", value=f"<@{g.host_id}>")
        embed.add_field(
            name="Manual winners",
            value=", ".join(f"<@{uid}>" for uid in g.manual_winner_ids) if g.manual_winner_ids else "Not set",
        )
        if g.winners:
            embed.add_field(name="Result", value=", ".join(f"<@{x}>" for x in g.winners), inline=False)
        embed.set_footer(text="This dashboard is private to you. Administrative actions are audited.")
        return embed

    @tasks.loop(seconds=15)
    async def check_due(self) -> None:
        for g in await self.db.due(int(time.time())):
            await self.end_giveaway(g.id)

    @check_due.before_loop
    async def before_check_due(self) -> None:
        await self.wait_until_ready()


def install_commands(bot: GiveawayBot) -> None:
    @bot.tree.command(name="gcreate", description="starts a giveaway (interactive)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gcreate(interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(CreateGiveawayModal(bot))

    @bot.tree.command(name="gstart", description="starts a giveaway (interactive)")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gstart(interaction: discord.Interaction) -> None:
        """Profile-friendly alias matching the reference bot's command list."""
        await interaction.response.send_modal(CreateGiveawayModal(bot))

    @bot.tree.command(name="gend", description="end a giveaway now")
    @app_commands.describe(giveaway_id="The giveaway ID shown at the bottom of its embed")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gend(interaction: discord.Interaction, giveaway_id: int) -> None:
        assert interaction.guild_id is not None
        giveaway = await bot.db.get(giveaway_id)
        if giveaway is None or giveaway.guild_id != interaction.guild_id:
            return await interaction.response.send_message("I could not find that giveaway in this server.", ephemeral=True)
        if giveaway.status != "active":
            return await interaction.response.send_message("That giveaway has already ended.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await bot.end_giveaway(giveaway.id, actor_id=interaction.user.id)
        await interaction.followup.send(f"Giveaway `{giveaway.id}` has ended.", ephemeral=True)

    @bot.tree.command(name="greroll", description="reroll an ended giveaway")
    @app_commands.describe(giveaway_id="The ended giveaway ID shown at the bottom of its embed")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def greroll(interaction: discord.Interaction, giveaway_id: int) -> None:
        assert interaction.guild_id is not None
        giveaway = await bot.db.get(giveaway_id)
        if giveaway is None or giveaway.guild_id != interaction.guild_id:
            return await interaction.response.send_message("I could not find that giveaway in this server.", ephemeral=True)
        if giveaway.status != "ended":
            return await interaction.response.send_message("That giveaway has not ended yet.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await bot.reroll_giveaway(giveaway.id, interaction.user.id)
        refreshed = await bot.db.get(giveaway.id)
        mentions = ", ".join(f"<@{uid}>" for uid in (refreshed.winners if refreshed else [])) or "No eligible entries"
        await interaction.followup.send(f"Giveaway `{giveaway.id}` rerolled randomly: {mentions}.", ephemeral=True)

    @bot.tree.command(name="ghelp", description="show the GiveawayBot command guide")
    @app_commands.guild_only()
    async def ghelp(interaction: discord.Interaction) -> None:
        embed = discord.Embed(title="GiveawayBot Commands", colour=BLUE)
        embed.description = (
            "`/gcreate` — open the giveaway creation form\n"
            "`/gstart` — open the same interactive creation form\n"
            "`/greroll <giveaway_id>` — randomly reroll an ended giveaway\n"
            "`/gend <giveaway_id>` — end an active giveaway now\n"
            "`/gdashboard` — open the private administrator dashboard\n\n"
            "Creation, ending, rerolling, and dashboard controls require **Manage Server**."
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @bot.tree.command(name="gdashboard", description="Open the private giveaway admin dashboard")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def gdashboard(interaction: discord.Interaction) -> None:
        assert interaction.guild_id is not None
        giveaways = await bot.db.list_dashboard(interaction.guild_id)
        if not giveaways:
            return await interaction.response.send_message("No giveaways yet. Use `/gcreate` first.", ephemeral=True)
        view = DashboardView(bot, giveaways)
        await interaction.response.send_message(embed=await bot.dashboard_embed(giveaways[0].id), view=view, ephemeral=True)

    async def command_error(interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        message = "You need the **Manage Server** permission to use this command."
        if not isinstance(error, app_commands.MissingPermissions):
            log.exception("Application command failed", exc_info=error)
            message = "The command failed. Check the bot log for details."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    bot.tree.on_error = command_error

