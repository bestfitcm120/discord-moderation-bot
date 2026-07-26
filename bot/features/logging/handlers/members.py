import discord
from datetime import timezone
from typing import Optional

from bot.utils.audit import get_audit_executor, executor_field


class MemberEventHandlers:
    @staticmethod
    async def member_join(member: discord.Member) -> discord.Embed:
        embed = discord.Embed(
            title="Member Joined",
            description=f"{member.mention} joined the server.",
            color=discord.Color.green(),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Account Created", value=f"<t:{int(member.created_at.timestamp())}:R>", inline=True)
        embed.add_field(name="Member Count", value=member.guild.member_count, inline=True)
        embed.set_footer(text=f"User ID: {member.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def member_leave(member: discord.Member) -> discord.Embed:
        roles = [r.mention for r in member.roles if r.name != "@everyone"]
        embed = discord.Embed(
            title="Member Left",
            description=f"{member.mention} left the server.",
            color=discord.Color.red(),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        if roles:
            embed.add_field(name="Roles", value=" ".join(roles[:10]) + ("..." if len(roles) > 10 else ""), inline=False)
        embed.add_field(
            name="Joined",
            value=f"<t:{int(member.joined_at.timestamp())}:R>" if member.joined_at else "Unknown",
            inline=True,
        )
        embed.set_footer(text=f"User ID: {member.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def member_ban(guild: discord.Guild, user: discord.User) -> discord.Embed:
        executor = await get_audit_executor(guild, discord.AuditLogAction.ban, target_id=user.id)
        embed = discord.Embed(
            title="Member Banned",
            description=f"{user.mention} was banned from the server.",
            color=discord.Color.dark_red(),
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Banned by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {user.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def member_unban(guild: discord.Guild, user: discord.User) -> discord.Embed:
        executor = await get_audit_executor(guild, discord.AuditLogAction.unban, target_id=user.id)
        embed = discord.Embed(
            title="Member Unbanned",
            description=f"{user.mention} was unbanned from the server.",
            color=discord.Color.green(),
        )
        embed.set_author(name=str(user), icon_url=user.display_avatar.url)
        embed.add_field(name="Unbanned by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {user.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def timeout_add(before: discord.Member, after: discord.Member) -> discord.Embed:
        executor = await get_audit_executor(after.guild, discord.AuditLogAction.member_update, target_id=after.id)
        embed = discord.Embed(
            title="Member Timed Out",
            description=f"{after.mention} has been timed out.",
            color=discord.Color.orange(),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        if after.timed_out_until:
            embed.add_field(
                name="Expires",
                value=f"<t:{int(after.timed_out_until.timestamp())}:R>",
                inline=True,
            )
        embed.add_field(name="Timed out by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {after.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def timeout_remove(before: discord.Member, after: discord.Member) -> discord.Embed:
        executor = await get_audit_executor(after.guild, discord.AuditLogAction.member_update, target_id=after.id)
        embed = discord.Embed(
            title="Timeout Removed",
            description=f"Timeout removed from {after.mention}.",
            color=discord.Color.green(),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        embed.add_field(name="Removed by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {after.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def member_kick(
        guild: discord.Guild,
        member: discord.Member,
        executor=None,
    ) -> discord.Embed:
        if executor is None:
            executor = await get_audit_executor(guild, discord.AuditLogAction.kick, target_id=member.id)
        embed = discord.Embed(
            title="Member Kicked",
            description=f"{member.mention} was kicked from the server.",
            color=discord.Color.orange(),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Kicked by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {member.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def nickname_change(before: discord.Member, after: discord.Member) -> discord.Embed:
        executor = await get_audit_executor(after.guild, discord.AuditLogAction.member_update, target_id=after.id)
        embed = discord.Embed(
            title="Nickname Changed",
            description=f"{after.mention}'s nickname was changed.",
            color=discord.Color.blue(),
        )
        embed.set_author(name=str(after), icon_url=after.display_avatar.url)
        embed.add_field(name="Before", value=before.nick or "*None*", inline=True)
        embed.add_field(name="After", value=after.nick or "*None*", inline=True)
        if executor:
            if executor.id != after.id:
                embed.add_field(name="Changed by", value=executor_field(executor), inline=False)
            else:
                embed.add_field(name="Changed by", value="Member themselves", inline=False)
        embed.set_footer(text=f"User ID: {after.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def role_given(member: discord.Member, role: discord.Role) -> discord.Embed:
        executor = await get_audit_executor(member.guild, discord.AuditLogAction.member_role_update, target_id=member.id)
        embed = discord.Embed(
            title="Role Given",
            description=f"{role.mention} was given to {member.mention}.",
            color=role.color if role.color.value else discord.Color.blurple(),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Given by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {member.id} | Role ID: {role.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed

    @staticmethod
    async def role_removed(member: discord.Member, role: discord.Role) -> discord.Embed:
        executor = await get_audit_executor(member.guild, discord.AuditLogAction.member_role_update, target_id=member.id)
        embed = discord.Embed(
            title="Role Removed",
            description=f"{role.mention} was removed from {member.mention}.",
            color=discord.Color.greyple(),
        )
        embed.set_author(name=str(member), icon_url=member.display_avatar.url)
        embed.add_field(name="Removed by", value=executor_field(executor), inline=False)
        embed.set_footer(text=f"User ID: {member.id} | Role ID: {role.id}")
        embed.timestamp = discord.utils.utcnow()
        return embed
