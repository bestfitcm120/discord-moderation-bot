import asyncio
import time
import discord
from typing import Optional, Union

# Tracks audit log entry IDs already attributed to a specific event so that
# when several members are moved/disconnected in the same short window we
# don't accidentally attribute the same admin action to more than one of them.
_consumed_entries: dict[int, float] = {}
_CONSUMED_TTL = 30.0


def _cleanup_consumed() -> None:
    now = time.monotonic()
    stale = [k for k, ts in _consumed_entries.items() if now - ts > _CONSUMED_TTL]
    for k in stale:
        _consumed_entries.pop(k, None)


async def get_audit_executor(
    guild: discord.Guild,
    action: discord.AuditLogAction,
    target_id: Optional[int] = None,
    channel_id: Optional[int] = None,
    max_age: float = 15.0,
    delay: float = 1.2,
    attempts: int = 4,
    retry_interval: float = 1.0,
    exclusive: bool = False,
) -> Optional[Union[discord.Member, discord.User]]:
    """
    Fetch the executor (who performed an action) from the audit log.

    Some voice-related audit actions (member_move, member_disconnect) do not
    include a per-member target in Discord's audit log payload — only a
    channel and a count. To reduce mis-attribution when several members are
    affected close together, we optionally match on the channel the action
    occurred in (`channel_id`) and, when `exclusive=True`, mark the matched
    entry as "consumed" so a second concurrent lookup won't reuse it.

    Retries a few times with a delay since Discord's audit log can take a
    moment to populate after the originating event fires — without retrying,
    a slightly slow audit log write gets silently treated as "no executor
    found", which looks identical to a self-initiated action.

    Returns None if not found, audit log is unavailable, or the bot lacks
    permission to view it.
    """
    _cleanup_consumed()

    for attempt in range(attempts):
        await asyncio.sleep(delay if attempt == 0 else retry_interval)
        try:
            async for entry in guild.audit_logs(limit=15, action=action):
                age = (discord.utils.utcnow() - entry.created_at).total_seconds()
                if age > max_age:
                    break

                if exclusive and entry.id in _consumed_entries:
                    continue

                if target_id is not None:
                    entry_target_id = getattr(entry.target, "id", None)
                    if entry_target_id is not None and entry_target_id != target_id:
                        continue

                if channel_id is not None:
                    entry_channel = getattr(entry.extra, "channel", None)
                    entry_channel_id = getattr(entry_channel, "id", None)
                    if entry_channel_id is not None and entry_channel_id != channel_id:
                        continue

                if exclusive:
                    _consumed_entries[entry.id] = time.monotonic()
                return entry.user
        except (discord.Forbidden, discord.HTTPException):
            return None

    return None


def executor_field(executor: Optional[Union[discord.Member, discord.User]]) -> str:
    """Format an executor mention for embed fields."""
    if executor:
        return f"{executor.mention} (`{executor}`)"
    return "*Unknown (no audit log access)*"
