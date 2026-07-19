---
name: Voice audit log attribution
description: How to correctly attribute who performed a voice disconnect/move in Discord's audit log
---

## The rule
`AuditLogAction.member_disconnect` and `member_move` audit entries do **not** carry a per-member `target` field — only `extra.channel` (the affected channel) and `extra.count`. You cannot filter them by victim user ID.

## Why
Discord treats these as bulk administrative actions. The audit log only records the channel and how many members were affected, not which specific members.

## How to apply
- Match by `entry.extra.channel.id == before.channel.id` (disconnect) or `after.channel.id` (move) to at least scope to the right channel.
- Use an in-memory `_consumed_entries` dict (entry.id → monotonic timestamp, TTL ~30s) with `exclusive=True` to prevent the same audit entry from being attributed to multiple simultaneous voice events in the same channel.
- Retry the audit log lookup (4 attempts, 1.2s initial delay, 1s between) because Discord's audit log propagation can lag the gateway event by several seconds.
- Wrap per-guild voice event processing in an `asyncio.Lock` (keyed by guild_id) inside LoggingCog so events finish in the order they arrived rather than whichever audit lookup resolves first.
