import discord
from typing import List, Tuple

from bot.utils.audit import get_audit_executor, executor_field


class ChannelEventHandlers:
    @staticmethod
    async def channel_create(channel: discord.abc.GuildChannel) -> discord.Embed:
        executor = await get_audit_executor(
            channel.guild, discord.AuditLogAction.channel_create, target_id=channel.id
        )
        embed = discord.Embed(
            title="Channel Created",
            description=f"New channel {channel.mention} was created.",
            color=discord.Color.green(),
        )
        embed.add_field(name="Name", value=channel.name, inline=True)
        embed.add_field(name="Type", value=str(channel.type).replace("_", " ").title(), inline=True)
        if hasattr(channel, "category") and channel.category:
            embed.add_field(name="Category", value=channel.category.name, inline=True)
        embed.add_field(name="Created by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"Channel ID: {channel.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def channel_delete(channel: discord.abc.GuildChannel) -> discord.Embed:
        executor = await get_audit_executor(
            channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id
        )
        embed = discord.Embed(
            title="Channel Deleted",
            description=f"Channel **#{channel.name}** was deleted.",
            color=discord.Color.red(),
        )
        embed.add_field(name="Name", value=channel.name, inline=True)
        embed.add_field(name="Type", value=str(channel.type).replace("_", " ").title(), inline=True)
        if hasattr(channel, "category") and channel.category:
            embed.add_field(name="Category", value=channel.category.name, inline=True)
        embed.add_field(name="Deleted by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"Channel ID: {channel.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed


    @staticmethod
    async def channel_update(
        before: discord.abc.GuildChannel,
        after: discord.abc.GuildChannel,
    ) -> List[Tuple[discord.Embed, str]]:
        results: List[Tuple[discord.Embed, str]] = []

        # Check for general changes (name, topic, etc.)
        general_changes: List[str] = []
        if before.name != after.name:
            general_changes.append(f"**Name:** {before.name} → {after.name}")
        if hasattr(before, "topic") and hasattr(after, "topic"):
            if before.topic != after.topic:
                general_changes.append(f"**Topic:** {before.topic or '*none*'} → {after.topic or '*none*'}")
        if hasattr(before, "slowmode_delay") and hasattr(after, "slowmode_delay"):
            if before.slowmode_delay != after.slowmode_delay:
                general_changes.append(f"**Slowmode:** {before.slowmode_delay}s → {after.slowmode_delay}s")
        if hasattr(before, "nsfw") and hasattr(after, "nsfw"):
            if before.nsfw != after.nsfw:
                general_changes.append(f"**NSFW:** {before.nsfw} → {after.nsfw}")

        if general_changes:
            executor = await get_audit_executor(
                after.guild, discord.AuditLogAction.channel_update, target_id=after.id
            )
            embed = discord.Embed(
                title="Channel Updated",
                description=f"Channel {after.mention} was updated.",
                color=discord.Color.blue(),
            )
            embed.add_field(name="Changes", value="\n".join(general_changes), inline=False)
            embed.add_field(name="Updated by", value=executor_field(executor), inline=False)
            embed.set_footer(text=f"Channel ID: {after.id}")
            embed.timestamp = discord.utils.utcnow()
            results.append((embed, "channel_update"))

        # Check for permission overwrites changes
        if before.overwrites != after.overwrites:
            executor = await get_audit_executor(
                after.guild, discord.AuditLogAction.overwrite_update, target_id=after.id
            )
            if executor is None:
                executor = await get_audit_executor(
                    after.guild, discord.AuditLogAction.overwrite_create, target_id=after.id, delay=0.0
                )
            if executor is None:
                executor = await get_audit_executor(
                    after.guild, discord.AuditLogAction.overwrite_delete, target_id=after.id, delay=0.0
                )

            embed = discord.Embed(
                title="Channel Permissions Updated",
                description=f"Permissions in {after.mention} were changed.",
                color=discord.Color.orange(),
            )
            added = set(after.overwrites.keys()) - set(before.overwrites.keys())
            removed = set(before.overwrites.keys()) - set(after.overwrites.keys())
            changed = {
                k for k in before.overwrites.keys() & after.overwrites.keys()
                if before.overwrites[k] != after.overwrites[k]
            }
            if added:
                embed.add_field(name="Overwrite Added", value=", ".join(str(t) for t in added), inline=False)
            if removed:
                embed.add_field(name="Overwrite Removed", value=", ".join(str(t) for t in removed), inline=False)
            if changed:
                embed.add_field(name="Overwrite Changed", value=", ".join(str(t) for t in changed), inline=False)
            embed.add_field(name="Updated by", value=executor_field(executor), inline=False)
            embed.set_footer(text=f"Channel ID: {after.id}")
            embed.timestamp = discord.utils.utcnow()
            results.append((embed, "channel_permissions_update"))

        return results
