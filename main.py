from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from giveaway_bot.bot import GiveawayBot, install_commands


def main() -> None:
    load_dotenv()
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise SystemExit("DISCORD_TOKEN is missing. Copy .env.example to .env and add your token.")
    guild_value = os.getenv("TEST_GUILD_ID", "").strip()
    test_guild_id = int(guild_value) if guild_value else None
    database_path = os.getenv("DATABASE_PATH", "data/giveaways.sqlite3")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    bot = GiveawayBot(database_path, test_guild_id)
    install_commands(bot)
    bot.run(token, log_handler=None)


if __name__ == "__main__":
    main()
