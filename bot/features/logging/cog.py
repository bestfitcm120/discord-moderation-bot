import asyncio
import datetime
import discord
from discord.ext import commands
import logging
from typing import Optional

from bot.core.database import (
    get_pool,
    get_log_channel,
    insert_log_entry,
    track_member_event,
    track_message_event,
)
from bot.features.logging.handlers.members import MemberEventHandlers
from bot.features.logging.handlers.messages import MessageEventHandlers
from bot.features.logging.handlers.roles import RoleEventHandlers
from bot.features.logging.handlers.channels import ChannelEventHandlers
from bot.features.logging.handlers.voice import VoiceEventHandlers
from bot.features.logging.handlers.server import ServerEventHandlers

logger = logging.getLogger(__name__)


class LoggingCog(commands.Cog, name="Logging"):
    """
    Handles all server event logging.
    Each event is recorded to the database and dispatched to the
    configured log channel for that event type.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = None
        # Serializes voice event processing per guild so that concurrent
        # audit-log lookups (each with their own delay/retry loop) can't
        # finish out of order and scramble the log channel / dashboard order.
        self._voice_locks: dict[int, asyncio.Lock] = {}

    def _get_voice_lock(self, guild_id: int) -> asyncio.Lock:
        lock = self._voice_locks.get(guild_id)
        if lock is None:
            lock = asyncio.Lock()
            self._voice_locks[guild_id] = lock
        return lock

    async def cog_load(self) -> None:
        self.pool = await get_pool(self.bot.config.database_url)
        logger.info("LoggingCog loaded, database pool ready.")

    async def cog_unload(self) -> None:
        pass

    async def send_log(
        self,
        guild: discord.Guild,
        event_type: str,
        embed: discord.Embed,
        user_id: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[dict] = None,
        event_time: Optional[datetime.datetime] = None,
    ) -> None:
        """
        Central dispatch: look up the configured channel, send the embed,
        and record the event in the database.

        `event_time` should be the moment the underlying Discord event fired
        (captured before any audit-log delay/await), so events recorded out
        of processing order still land in the right chronological order in
        the database / dashboard.
        """
        channel_id = await get_log_channel(self.pool, str(guild.id), event_type)
        if channel_id:
            channel = guild.get_channel(int(channel_id))
            if channel and isinstance(channel, discord.TextChannel):
                try:
                    await channel.send(embed=embed)
                except discord.Forbidden:
                    logger.warning(
                        f"No permission to send to channel {channel_id} in guild {guild.id}"
                    )
                except discord.HTTPException as e:
                    logger.error(f"Failed to send log to channel {channel_id}: {e}")

        await insert_log_entry(
            self.pool,
            guild_id=str(guild.id),
            event_type=event_type,
            description=embed.description or "",
            user_id=user_id,
            target_id=target_id,
            metadata=metadata or {},
            created_at=event_time,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Member events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        await track_member_event(self.pool, str(member.guild.id), str(member.id), "join")
        embed = await MemberEventHandlers.member_join(member)
        await self.send_log(
            member.guild, "member_join", embed,
            user_id=str(member.id), metadata={"account_created": str(member.created_at)}
        )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        await track_member_event(self.pool, str(member.guild.id), str(member.id), "leave")
        embed = await MemberEventHandlers.member_leave(member)
        await self.send_log(
            member.guild, "member_leave", embed,
            user_id=str(member.id)
        )

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = await MemberEventHandlers.member_ban(guild, user)
        await self.send_log(
            guild, "member_ban", embed,
            target_id=str(user.id), metadata={"username": str(user)}
        )

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User) -> None:
        embed = await MemberEventHandlers.member_unban(guild, user)
        await self.send_log(
            guild, "member_unban", embed,
            target_id=str(user.id), metadata={"username": str(user)}
        )

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        guild = after.guild

        # Timeout added or removed
        if before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                embed = await MemberEventHandlers.timeout_add(before, after)
                await self.send_log(
                    guild, "member_timeout_add", embed,
                    target_id=str(after.id),
                    metadata={"until": str(after.timed_out_until)}
                )
            else:
                embed = await MemberEventHandlers.timeout_remove(before, after)
                await self.send_log(
                    guild, "member_timeout_remove", embed,
                    target_id=str(after.id)
                )

        # Nickname changed
        if before.nick != after.nick:
            embed = await MemberEventHandlers.nickname_change(before, after)
            await self.send_log(
                guild, "member_nickname_change", embed,
                user_id=str(after.id),
                metadata={"old_nick": before.nick, "new_nick": after.nick}
            )

        # Roles changed
        added_roles = set(after.roles) - set(before.roles)
        removed_roles = set(before.roles) - set(after.roles)

        for role in added_roles:
            embed = await MemberEventHandlers.role_given(after, role)
            await self.send_log(
                guild, "member_role_add", embed,
                user_id=str(after.id), target_id=str(role.id),
                metadata={"role_name": role.name}
            )

        for role in removed_roles:
            embed = await MemberEventHandlers.role_removed(after, role)
            await self.send_log(
                guild, "member_role_remove", embed,
                user_id=str(after.id), target_id=str(role.id),
                metadata={"role_name": role.name}
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Message events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild and not message.author.bot:
            await track_message_event(
                self.pool,
                str(message.guild.id),
                str(message.channel.id),
                str(message.author.id),
                False,
            )

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message) -> None:
        if not message.guild or message.author.bot:
            return
        embed = await MessageEventHandlers.message_delete(message)
        await self.send_log(
            message.guild, "message_delete", embed,
            user_id=str(message.author.id),
            metadata={"channel": message.channel.name, "content": message.content[:500]}
        )

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message) -> None:
        if not after.guild or after.author.bot or before.content == after.content:
            return
        embed = await MessageEventHandlers.message_edit(before, after)
        await self.send_log(
            after.guild, "message_edit", embed,
            user_id=str(after.author.id),
            metadata={
                "channel": after.channel.name,
                "before": before.content[:500],
                "after": after.content[:500],
            }
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Role events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role) -> None:
        embed = await RoleEventHandlers.role_create(role)
        await self.send_log(
            role.guild, "role_create", embed,
            target_id=str(role.id), metadata={"role_name": role.name}
        )

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role) -> None:
        embed = await RoleEventHandlers.role_delete(role)
        await self.send_log(
            role.guild, "role_delete", embed,
            target_id=str(role.id), metadata={"role_name": role.name}
        )

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role) -> None:
        embed = await RoleEventHandlers.role_update(before, after)
        await self.send_log(
            after.guild, "role_update", embed,
            target_id=str(after.id), metadata={"role_name": after.name}
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Channel events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel) -> None:
        embeds = await ChannelEventHandlers.channel_update(before, after)
        for embed, event_type in embeds:
            await self.send_log(
                after.guild, event_type, embed,
                target_id=str(after.id), metadata={"channel_name": after.name}
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Voice events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # Capture the moment the event actually happened, before any
        # audit-log delay, so ordering stays correct even if a later event
        # finishes processing first.
        event_time = discord.utils.utcnow()
        lock = self._get_voice_lock(member.guild.id)
        async with lock:
            embeds = await VoiceEventHandlers.voice_state_update(member, before, after)
            for embed, event_type in embeds:
                await self.send_log(
                    member.guild, event_type, embed,
                    user_id=str(member.id),
                    event_time=event_time,
                )

    # ──────────────────────────────────────────────────────────────────────────
    # Server events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild) -> None:
        embed = await ServerEventHandlers.server_update(before, after)
        await self.send_log(after, "server_update", embed)

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite) -> None:
        embed = await ServerEventHandlers.invite_create(invite)
        await self.send_log(
            invite.guild, "invite_create", embed,
            user_id=str(invite.inviter.id) if invite.inviter else None,
            metadata={"code": invite.code, "max_uses": invite.max_uses}
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Command events
    # ──────────────────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command,
    ) -> None:
        if not interaction.guild:
            return
        embed = discord.Embed(
            title="Command Used",
            description=f"{interaction.user.mention} used `/{command.name}` in {interaction.channel.mention}",
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"User ID: {interaction.user.id}")
        await self.send_log(
            interaction.guild, "command_used", embed,
            user_id=str(interaction.user.id),
            metadata={"command": command.name}
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LoggingCog(bot))
