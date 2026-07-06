"""
/dashboard-access command group — lets a sufficiently high-permission member
control who can access the web dashboard for this server, beyond Discord's
own Manage Server / Administrator permission.
"""
import discord
from discord import app_commands
from discord.ext import commands
import logging
from typing import Optional

from bot.core.database import (
    get_pool,
    add_dashboard_access,
    remove_dashboard_access,
    list_dashboard_access,
)

logger = logging.getLogger(__name__)


def _can_manage_dashboard_access(interaction: discord.Interaction) -> bool:
    """
    Only allow members who have Administrator permission, OR whose highest
    role outranks the bot's highest role, to manage dashboard access.
    Either condition is sufficient — this keeps the bar at "at least as
    trusted as an administrator, or someone the bot itself already defers to".
    """
    member = interaction.user
    guild = interaction.guild
    if guild is None or not isinstance(member, discord.Member):
        return False

    if member.guild_permissions.administrator:
        return True

    bot_member = guild.me
    if bot_member and member.top_role.position > bot_member.top_role.position:
        return True

    return False


class DashboardAccessCheckFailure(app_commands.CheckFailure):
    pass


def _require_dashboard_permission():
    def predicate(interaction: discord.Interaction) -> bool:
        if _can_manage_dashboard_access(interaction):
            return True
        raise DashboardAccessCheckFailure(
            "You need Administrator permission, or a role higher than mine, to manage dashboard access."
        )
    return app_commands.check(predicate)


class DashboardAccessGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot):
        super().__init__(name="dashboard-access", description="Control who can access the web dashboard.")
        self.bot = bot

    async def _pool(self):
        return await get_pool(self.bot.config.database_url)

    @app_commands.command(name="add", description="Allow a role or member to access the web dashboard.")
    @app_commands.describe(
        role="A role whose members should get dashboard access",
        member="A specific member who should get dashboard access",
    )
    @_require_dashboard_permission()
    @app_commands.guild_only()
    async def add(
        self,
        interaction: discord.Interaction,
        role: Optional[discord.Role] = None,
        member: Optional[discord.Member] = None,
    ) -> None:
        if (role is None) == (member is None):
            await interaction.response.send_message(
                "Provide exactly one of `role` or `member`.", ephemeral=True
            )
            return

        pool = await self._pool()
        target_type = "role" if role else "user"
        target_id = str(role.id) if role else str(member.id)
        target_label = role.mention if role else member.mention

        added = await add_dashboard_access(
            pool, str(interaction.guild.id), target_type, target_id, str(interaction.user.id)
        )
        if added:
            await interaction.response.send_message(
                f"✅ {target_label} can now access the web dashboard.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{target_label} already has dashboard access.", ephemeral=True
            )

    @app_commands.command(name="remove", description="Revoke web dashboard access from a role or member.")
    @app_commands.describe(
        role="A role to revoke dashboard access from",
        member="A specific member to revoke dashboard access from",
    )
    @_require_dashboard_permission()
    @app_commands.guild_only()
    async def remove(
        self,
        interaction: discord.Interaction,
        role: Optional[discord.Role] = None,
        member: Optional[discord.Member] = None,
    ) -> None:
        if (role is None) == (member is None):
            await interaction.response.send_message(
                "Provide exactly one of `role` or `member`.", ephemeral=True
            )
            return

        pool = await self._pool()
        target_type = "role" if role else "user"
        target_id = str(role.id) if role else str(member.id)
        target_label = role.mention if role else member.mention

        removed = await remove_dashboard_access(pool, str(interaction.guild.id), target_type, target_id)
        if removed:
            await interaction.response.send_message(
                f"🗑️ Removed dashboard access for {target_label}.", ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"{target_label} didn't have dashboard access.", ephemeral=True
            )

    @app_commands.command(name="list", description="Show who currently has web dashboard access.")
    @_require_dashboard_permission()
    @app_commands.guild_only()
    async def list_access(self, interaction: discord.Interaction) -> None:
        pool = await self._pool()
        entries = await list_dashboard_access(pool, str(interaction.guild.id))

        embed = discord.Embed(
            title="Dashboard Access",
            color=discord.Color.blurple(),
        )
        embed.description = (
            "Anyone with **Manage Server** or **Administrator** permission always has access.\n"
            "Additionally granted roles/members:"
        )

        if not entries:
            embed.add_field(name="\u200b", value="*No additional roles or members granted.*", inline=False)
        else:
            lines = []
            for e in entries:
                if e["target_type"] == "role":
                    lines.append(f"• Role <@&{e['target_id']}>")
                else:
                    lines.append(f"• Member <@{e['target_id']}>")
            embed.add_field(name="\u200b", value="\n".join(lines), inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    async def on_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, DashboardAccessCheckFailure):
            await interaction.response.send_message(f"⛔ {error}", ephemeral=True)
        else:
            logger.error(f"dashboard-access command error: {error}", exc_info=True)
            if not interaction.response.is_done():
                await interaction.response.send_message(
                    "Something went wrong running that command.", ephemeral=True
                )


async def setup(bot: commands.Bot) -> None:
    bot.tree.add_command(DashboardAccessGroup(bot))
