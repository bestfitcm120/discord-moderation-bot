---
name: Dashboard access gating pattern
description: How per-guild access control works across the web API
---

## The rule
`_user_can_access_guild(guild_id, session)` in `web/features/guilds/router.py` is the single source of truth. It checks:
1. Discord Manage Server (0x20) or Administrator (0x8) bit in user's guild permissions (from `/users/@me/guilds` via their OAuth access_token), **OR**
2. An explicit grant row in `dashboard_access` table — direct user match first, then role match via `GET /guilds/{guild_id}/members/{user_id}` bot-token call.

## Why
- Server owners can designate trusted roles/users who lack Discord admin perms but should still reach the dashboard (managed via `/dashboard-access add` bot slash command).
- The check is applied to every per-guild endpoint in both `guilds/router.py` and `config/router.py` (imported from guilds router).

## How to apply
- Import `_user_can_access_guild` from `web.features.guilds.router` into any new router module that handles guild-scoped endpoints.
- Always call `if not await _user_can_access_guild(guild_id, session): return JSONResponse({"error": "Forbidden"}, status_code=403)` immediately after the `_require_session` check.
- `list_guilds` (GET /guilds) uses an async gather over the same check to decide which guilds appear in the server list — keep both in sync.
