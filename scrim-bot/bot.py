import logging
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv

import db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("scrim-bot")

load_dotenv(Path(__file__).parent / ".env")
TOKEN = os.environ.get("DISCORD_TOKEN")
if not TOKEN:
    raise SystemExit(".env에 DISCORD_TOKEN을 설정해주세요.")

_dev_guild_raw = os.environ.get("DEV_GUILD_ID")
DEV_GUILD = discord.Object(id=int(_dev_guild_raw)) if _dev_guild_raw else None


class ScrimBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self) -> None:
        db.init_db()
        log.info("DB initialized at %s", db.DB_PATH)

        await self.load_extension("cogs.scrim")
        log.info("Loaded cog: scrim")

        if DEV_GUILD is not None:
            self.tree.copy_global_to(guild=DEV_GUILD)
            synced = await self.tree.sync(guild=DEV_GUILD)
            log.info("Synced %d commands to guild %s", len(synced), DEV_GUILD.id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d commands globally", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)


bot = ScrimBot()


if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
