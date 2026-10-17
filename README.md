# GiveawayBot (discord.py)

A restart-safe Discord giveaway bot modeled on the supplied screenshots. It provides:

- `/gcreate` and `/gstart` with a native Discord modal: **Duration**, **Number of Winners**, **Prize**, and **Description**
- a compact Discord embed with relative/absolute end time, host, entry count, winner count, and a blue 🎉 entry button
- local SQLite storage with no account, server, or cloud database required
- automatic endings after restarts and downtime
- a private, ephemeral `/gdashboard` for server managers
- end-now, random reroll, and explicitly labeled manual/predetermined winners
- an audit log in SQLite for administrative actions
- a normal online Discord presence while the bot is connected

Manual winner selection is not disguised as a random draw. When one is configured, the live embed and final result label the selection method as manual/predetermined. Rerolls are always random from eligible entrants who did not win the prior draw.

## 1. Create the Discord bot

1. Open the [Discord Developer Portal](https://discord.com/developers/applications), create an application, then open **Bot** and create its bot user.
2. Copy the token. Never post it or commit `.env`.
3. Under **Privileged Gateway Intents**, enable **Server Members Intent**. This allows exact member-name lookup. Member IDs work regardless.
4. Upload the avatar in the bot profile settings. Discord controls the profile card UI. If Discord offers a banner setting for your application/account, upload it there; a running bot cannot set its own banner through `discord.py`.
5. In **OAuth2 → URL Generator**, select `bot` and `applications.commands`. Recommended bot permissions: **View Channels**, **Send Messages**, **Embed Links**, **Read Message History**, and **Use External Emojis**.

The bot starts with a normal online presence. If it still appears offline, verify that the launcher window remains open, the token is valid, and the log says the bot connected successfully.

## 2. Install and configure

### Easy Windows setup

Double-click **`setup-and-run.bat`**. It creates a private Python environment, installs or updates all requirements, creates `.env`, opens it for your Discord token, and starts the bot. After the first setup, double-click the same file whenever you want to run the bot.

If Windows says Python is missing, install Python 3.11 or newer and enable **Add Python to PATH** in the installer.

### Manual setup

Python 3.11 or newer is recommended. In PowerShell, from this project folder:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -r requirements.txt
Copy-Item .env.example .env
notepad .env
```

Set `DISCORD_TOKEN` in `.env`. For quick command updates while testing, put your server ID in `TEST_GUILD_ID`. To copy a server ID, enable Discord Developer Mode, right-click the server, and choose **Copy Server ID**. Remove it later if you want global commands; global registration can take longer to appear.

Run the bot:

```powershell
py main.py
```

## 3. Use it

- `/gcreate` — server managers get the four-field modal. Duration accepts `10m`, `2h 30m`, `1 day`, and similar forms.
- `/gstart` — opens the same interactive creation form, matching the reference bot's profile command list.
- `/gend <giveaway_id>` — ends an active giveaway immediately.
- `/greroll <giveaway_id>` — randomly rerolls an ended giveaway.
- `/ghelp` — displays a private command guide.
- Press 🎉 — toggles the member's entry and privately confirms the action.
- `/gdashboard` — opens an ephemeral dashboard visible only to the manager who invoked it.
- **Manual winners in `/gcreate`** — the optional fifth field accepts one or more Discord user IDs, exact usernames, or exact server display names separated by commas.
- **Set manual winner** — the dashboard accepts the same comma-separated list. The live giveaway is then labeled manual/predetermined.
- **Clear manual** — returns an active giveaway to random selection.
- **End now** — ends the selected active giveaway immediately.
- **Reroll** — randomly selects new winners from the remaining entrants of an ended giveaway.

Only members with **Manage Server** can use creation and dashboard commands.

### Showing commands on the bot profile

Discord automatically builds the **Commands** section on the bot profile from its registered global application commands; it is not part of the editable About Me text. Invite the bot with the `applications.commands` scope, leave `TEST_GUILD_ID` empty, and restart it once to register the commands globally. Discord can take a while to show newly registered global commands. During development, setting `TEST_GUILD_ID` makes commands appear quickly in that server, but server-only test commands may not appear on the public profile card in the same way.

## Local persistence and restarts

The database defaults to `data/giveaways.sqlite3` on the same PC. SQLite is embedded in the application: there is no login, subscription, separate service, or setup program. Back up that single file while the bot is stopped if you want an external copy.

Every 15 seconds the bot checks for due giveaways. On startup it restores the persistent 🎉 handler, reads active giveaways from SQLite, and ends overdue ones as soon as Discord reports the bot ready. Entries, chosen manual winner, results, and audit rows all survive restarts.

## 24/7 Railway hosting

The included `Dockerfile` and `railway.json` make the project ready for Railway deployment.

1. Create/connect a Railway account and create a project from this source folder or a GitHub repository containing it.
2. Add the private service variable `DISCORD_TOKEN` with the bot token. Optionally add `TEST_GUILD_ID`; leave it empty for global commands.
3. Add a Railway Volume mounted at `/data`. The image already sets `DATABASE_PATH=/data/giveaways.sqlite3`, so entries and giveaways survive deployments and restarts.
4. Deploy one replica and check the logs for a successful Discord connection. Do not run the local BAT at the same time with the same token; Discord should have only one copy of this bot process connected.

Never commit `.env` or paste the bot token into source code. If a token is exposed, reset it immediately in Discord's Developer Portal and update the Railway variable.

## Tests

```powershell
py -m pip install -r requirements-dev.txt
py -m pytest -q
```

Tests cover duration parsing, winner selection, entry toggling, one-time endings, and persistence after reopening the database.

## Notes

- Keep the computer and process running for endings to happen at the exact time. If it is offline, the giveaway finishes after the bot reconnects.
- The dashboard is ephemeral, but Discord administrators and anyone with access to the PC/database can still inspect administrative records.
- Native modal colors, fonts, spacing, safety notice, and buttons are rendered by the user's Discord client and cannot be pixel-controlled by a bot.
