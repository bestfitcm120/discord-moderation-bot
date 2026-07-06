import asyncio
import discord
from discord.ext import commands
import logging
import os

from bot.core.config import BotConfig

logger = logging.getLogger(__name__)

HEALTHY_FILE = "/tmp/healthy"


class ModerationBot(commands.Bot):
    def __init__(self, config: BotConfig):
        self.config = config
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.guilds = True
        intents.voice_states = True
        intents.moderation = True
        intents.invites = True

        super().__init__(
            command_prefix=config.prefix,
            intents=intents,
            help_command=None,
        )

    async def setup_hook(self) -> None:
        await self._load_features()
        logger.info("Bot setup complete — guild-specific command sync will run on_ready.")

    async def _load_features(self) -> None:
        extensions = [
            "bot.features.logging.cog",
            "bot.features.moderation.cog",
            "bot.features.temp_voice.cog",
            "bot.features.leveling.cog",
            "bot.features.dashboard_access.cog",
        ]
        for ext in extensions:
            try:
                await self.load_extension(ext)
                logger.info(f"Loaded extension: {ext}")
            except Exception as e:
                logger.error(f"Failed to load extension {ext}: {e}", exc_info=True)

    async def on_ready(self) -> None:
        logger.info(f"Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"{len(self.guilds)} servers",
            )
        )
        # Sync commands as guild-specific so they appear instantly (no global propagation delay).
        # We do NOT call tree.sync() globally — that would create duplicate commands alongside
        # the guild-specific ones already registered via copy_global_to.
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                logger.info(f"Synced commands to guild: {guild.name} ({guild.id})")
            except Exception as e:
                logger.warning(f"Failed to sync commands to guild {guild.id}: {e}")

        # Write initial heartbeat then start background refresh
        self._write_heartbeat()
        self.loop.create_task(self._heartbeat_loop())

    def _write_heartbeat(self) -> None:
        try:
            with open(HEALTHY_FILE, "w") as f:
                f.write("ok")
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        """Refresh the health file every 30 s so Docker knows the bot is alive."""
        while not self.is_closed():
            await asyncio.sleep(30)
            self._write_heartbeat()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        logger.info(f"Joined guild: {guild.name} (ID: {guild.id})")
        try:
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logger.info(f"Synced commands to new guild: {guild.name} ({guild.id})")
        except Exception as e:
            logger.warning(f"Failed to sync commands to new guild {guild.id}: {e}")

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        logger.info(f"Left guild: {guild.name} (ID: {guild.id})")
