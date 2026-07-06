import asyncio
import discord
from typing import List, Tuple, Optional

from bot.utils.audit import get_audit_executor, executor_field


class VoiceEventHandlers:
    @staticmethod
    async def voice_state_update(
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> List[Tuple[discord.Embed, str]]:
        results: List[Tuple[discord.Embed, str]] = []
        guild = member.guild

        # Member moved from one channel to another
        if before.channel and after.channel and before.channel != after.channel:
            # Discord's audit log doesn't record *which* member was moved for
            # member_move entries — only the destination channel and a count.
            # We match on the destination channel and mark the entry as
            # "consumed" so simultaneous moves of different members don't all
            # get attributed to the same admin action.
            executor = await get_audit_executor(
                guild,
                discord.AuditLogAction.member_move,
                channel_id=after.channel.id,
                exclusive=True,
            )

            # Skip moves initiated by the bot itself — these are temp-VC system moves
            # (e.g. moving a member from the creation channel into their new temp VC).
            if executor and executor.id == guild.me.id:
                return results

            if executor and executor.id != member.id:
                description = (
                    f"{member.mention} was moved from **{before.channel.name}** to **{after.channel.name}** "
                    f"by {executor.mention} (`{executor}`)."
                )
                title = "Member Moved Voice Channel (by Admin)"
            else:
                description = (
                    f"{member.mention} moved from **{before.channel.name}** to **{after.channel.name}**."
                )
                title = "Member Moved Voice Channel"

            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.blue(),
            )
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            embed.timestamp = discord.utils.utcnow()
            results.append((embed, "member_voice_move"))

        # Member disconnected from voice
        elif before.channel and not after.channel:
            # Same limitation as above: member_disconnect audit entries only
            # carry the source channel + count, not the specific member. We
            # match on the channel the member was disconnected from and
            # consume the entry so it can't be reused for another member.
            executor = await get_audit_executor(
                guild,
                discord.AuditLogAction.member_disconnect,
                channel_id=before.channel.id,
                exclusive=True,
            )

            if executor and executor.id != member.id:
                description = (
                    f"{member.mention} was disconnected from **{before.channel.name}** "
                    f"by {executor.mention} (`{executor}`)."
                )
                title = "Member Disconnected from Voice (by Admin)"
            else:
                description = (
                    f"{member.mention} disconnected from **{before.channel.name}**."
                )
                title = "Member Disconnected from Voice"

            embed = discord.Embed(
                title=title,
                description=description,
                color=discord.Color.dark_red(),
            )
            embed.set_author(name=str(member), icon_url=member.display_avatar.url)
            embed.set_footer(text=f"User ID: {member.id}")
            embed.timestamp = discord.utils.utcnow()
            results.append((embed, "member_voice_disconnect"))

        return results
