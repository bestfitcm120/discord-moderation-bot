import aiohttp
import os
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from typing import Optional

from web.core.session import get_session

router = APIRouter()

DISCORD_API = "https://discord.com/api/v10"


def _require_session(request: Request) -> Optional[dict]:
    session = get_session(request)
    return session


def _guild_icon_url(guild_id: str, icon: Optional[str]) -> Optional[str]:
    if not icon:
        return None
    return f"https://cdn.discordapp.com/icons/{guild_id}/{icon}.png"


async def _fetch_user_guilds(access_token: str) -> list:
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as resp:
            if resp.status != 200:
                return []
            return await resp.json()


async def _fetch_guild_member(guild_id: str, user_id: str) -> Optional[dict]:
    """Fetch a guild member object (including role IDs) using the bot token."""
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API}/guilds/{guild_id}/members/{user_id}",
            headers={"Authorization": f"Bot {bot_token}"},
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()


async def _has_dashboard_access_grant(guild_id: str, user_id: str) -> bool:
    """Check the dashboard_access table (role or direct user grants)."""
    from web.core.database import get_pool
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT target_type, target_id FROM dashboard_access WHERE guild_id = $1",
        guild_id,
    )
    if not rows:
        return False
    if any(r["target_type"] == "user" and r["target_id"] == user_id for r in rows):
        return True
    role_ids = {r["target_id"] for r in rows if r["target_type"] == "role"}
    if not role_ids:
        return False
    member = await _fetch_guild_member(guild_id, user_id)
    if not member:
        return False
    member_role_ids = set(member.get("roles", []))
    return bool(role_ids & member_role_ids)


async def _user_can_access_guild(guild_id: str, session: dict) -> bool:
    """
    A user can access a guild's dashboard pages if they have Discord's
    Manage Server / Administrator permission there, OR if they've been
    explicitly granted access (directly or via a role) through the
    /dashboard-access bot command.
    """
    user_guilds = await _fetch_user_guilds(session["access_token"])
    g = next((x for x in user_guilds if x["id"] == guild_id), None)
    if g:
        perms = int(g["permissions"])
        if perms & 0x20 or perms & 0x8:
            return True
    return await _has_dashboard_access_grant(guild_id, session["user_id"])


async def _fetch_discord_user(user_id: str) -> Optional[dict]:
    """Fetch a Discord user object by ID using the bot token."""
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API}/users/{user_id}",
            headers={"Authorization": f"Bot {bot_token}"},
        ) as resp:
            if resp.status != 200:
                return None
            return await resp.json()


async def _fetch_bot_guilds() -> set:
    """Return set of guild IDs the bot is in."""
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API}/users/@me/guilds",
            headers={"Authorization": f"Bot {bot_token}"},
        ) as resp:
            if resp.status != 200:
                return set()
            guilds = await resp.json()
            return {g["id"] for g in guilds}


async def _fetch_guild_channels(guild_id: str) -> list:
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{DISCORD_API}/guilds/{guild_id}/channels",
            headers={"Authorization": f"Bot {bot_token}"},
        ) as resp:
            if resp.status != 200:
                return []
            channels = await resp.json()
            return [
                {"id": c["id"], "name": c["name"], "type": c["type"]}
                for c in channels
                if c["type"] in (0, 2, 5)
            ]


@router.get("")
async def list_guilds(request: Request):
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    user_guilds = await _fetch_user_guilds(session["access_token"])
    bot_guild_ids = await _fetch_bot_guilds()

    MANAGE_GUILD = 0x20

    async def _is_permitted(g: dict) -> bool:
        perms = int(g["permissions"])
        if perms & MANAGE_GUILD or perms & 0x8:
            return True
        # Fall back to explicit dashboard-access grants (role or user),
        # only worth checking if the bot is actually present in the guild.
        if g["id"] not in bot_guild_ids:
            return False
        return await _has_dashboard_access_grant(g["id"], session["user_id"])

    import asyncio as _asyncio
    permitted_flags = await _asyncio.gather(*[_is_permitted(g) for g in user_guilds])
    managed = [g for g, ok in zip(user_guilds, permitted_flags) if ok]

    return [
        {
            "id": g["id"],
            "name": g["name"],
            "icon": g.get("icon"),
            "iconUrl": _guild_icon_url(g["id"], g.get("icon")),
            "memberCount": 0,
            "botPresent": g["id"] in bot_guild_ids,
        }
        for g in managed
    ]


@router.get("/{guild_id}")
async def get_guild(guild_id: str, request: Request):
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    async with aiohttp.ClientSession() as http:
        async with http.get(
            f"{DISCORD_API}/guilds/{guild_id}?with_counts=true",
            headers={"Authorization": f"Bot {bot_token}"},
        ) as resp:
            if resp.status == 403:
                return JSONResponse({"error": "Forbidden"}, status_code=403)
            if resp.status == 404:
                return JSONResponse({"error": "Guild not found"}, status_code=404)
            g = await resp.json()

    return {
        "id": g["id"],
        "name": g["name"],
        "icon": g.get("icon"),
        "iconUrl": _guild_icon_url(g["id"], g.get("icon")),
        "memberCount": g.get("approximate_member_count", 0),
        "description": g.get("description"),
    }


@router.get("/{guild_id}/channels")
async def list_guild_channels(guild_id: str, request: Request):
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    return await _fetch_guild_channels(guild_id)


@router.get("/{guild_id}/logs")
async def list_guild_logs(guild_id: str, request: Request):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, guild_id, event_type, user_id, target_id, description, metadata, created_at
        FROM log_entries
        WHERE guild_id = $1
        ORDER BY created_at DESC
        LIMIT 50
        """,
        guild_id,
    )
    return [
        {
            "id": r["id"],
            "guildId": r["guild_id"],
            "eventType": r["event_type"],
            "userId": r["user_id"],
            "targetId": r["target_id"],
            "description": r["description"],
            "metadata": r["metadata"],
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/{guild_id}/moderation")
async def list_guild_moderation(guild_id: str, request: Request, userId: Optional[str] = None):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    moderation_event_types = (
        "member_ban", "member_unban", "member_kick",
        "member_timeout_add", "member_timeout_remove", "member_warn",
    )

    if userId:
        rows = await pool.fetch(
            """
            SELECT id, guild_id, event_type, user_id, target_id, description, metadata, created_at
            FROM log_entries
            WHERE guild_id = $1
              AND event_type = ANY($2)
              AND target_id = $3
            ORDER BY created_at DESC
            LIMIT 100
            """,
            guild_id,
            list(moderation_event_types),
            userId,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, guild_id, event_type, user_id, target_id, description, metadata, created_at
            FROM log_entries
            WHERE guild_id = $1
              AND event_type = ANY($2)
            ORDER BY created_at DESC
            LIMIT 100
            """,
            guild_id,
            list(moderation_event_types),
        )

    import asyncio as _asyncio

    ids_to_resolve: set = set()
    for r in rows:
        if r["user_id"]:
            ids_to_resolve.add(r["user_id"])
        if r["target_id"]:
            ids_to_resolve.add(r["target_id"])

    user_cache: dict = {}
    if ids_to_resolve:
        fetched = await _asyncio.gather(*[_fetch_discord_user(uid) for uid in ids_to_resolve])
        for u in fetched:
            if u:
                user_cache[u["id"]] = u

    def _display(uid: Optional[str]) -> Optional[str]:
        if not uid:
            return None
        u = user_cache.get(uid)
        return (u.get("global_name") or u.get("username")) if u else None

    def _avatar(uid: Optional[str]) -> Optional[str]:
        if not uid:
            return None
        u = user_cache.get(uid)
        if not u or not u.get("avatar"):
            return None
        return f"https://cdn.discordapp.com/avatars/{u['id']}/{u['avatar']}.png?size=64"

    return [
        {
            "id": r["id"],
            "guildId": r["guild_id"],
            "eventType": r["event_type"],
            "userId": r["user_id"],
            "targetId": r["target_id"],
            "targetDisplayName": _display(r["target_id"]),
            "targetAvatarUrl": _avatar(r["target_id"]),
            "actorDisplayName": _display(r["user_id"]),
            "description": r["description"],
            "metadata": r["metadata"],
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/{guild_id}/warnings/{user_id}")
async def list_user_warnings(guild_id: str, user_id: str, request: Request):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, guild_id, event_type, user_id, target_id, description, metadata, created_at
        FROM log_entries
        WHERE guild_id = $1
          AND event_type = 'member_warn'
          AND target_id = $2
        ORDER BY created_at DESC
        """,
        guild_id,
        user_id,
    )
    return [
        {
            "id": r["id"],
            "guildId": r["guild_id"],
            "eventType": r["event_type"],
            "userId": r["user_id"],
            "targetId": r["target_id"],
            "description": r["description"],
            "metadata": r["metadata"],
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/{guild_id}/leveling-config")
async def get_leveling_config_route(guild_id: str, request: Request):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM leveling_config WHERE guild_id = $1",
        guild_id,
    )
    if row:
        return {
            "guildId": row["guild_id"],
            "textXpMin": row["text_xp_min"],
            "textXpMax": row["text_xp_max"],
            "textXpCooldown": row["text_xp_cooldown"],
            "voiceXpPerMinute": row["voice_xp_per_minute"],
            "levelupChannelId": row["levelup_channel_id"],
            "levelupMessageEnabled": row["levelup_message_enabled"],
        }
    return {
        "guildId": guild_id,
        "textXpMin": 15,
        "textXpMax": 25,
        "textXpCooldown": 60,
        "voiceXpPerMinute": 10,
        "levelupChannelId": None,
        "levelupMessageEnabled": True,
    }


@router.put("/{guild_id}/leveling-config")
async def update_leveling_config_route(guild_id: str, request: Request):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    body = await request.json()
    pool = get_pool()

    await pool.execute(
        """
        INSERT INTO leveling_config (
            guild_id, text_xp_min, text_xp_max, text_xp_cooldown,
            voice_xp_per_minute, levelup_channel_id, levelup_message_enabled, updated_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
        ON CONFLICT (guild_id) DO UPDATE SET
            text_xp_min             = EXCLUDED.text_xp_min,
            text_xp_max             = EXCLUDED.text_xp_max,
            text_xp_cooldown        = EXCLUDED.text_xp_cooldown,
            voice_xp_per_minute     = EXCLUDED.voice_xp_per_minute,
            levelup_channel_id      = EXCLUDED.levelup_channel_id,
            levelup_message_enabled = EXCLUDED.levelup_message_enabled,
            updated_at              = NOW()
        """,
        guild_id,
        body.get("textXpMin", 15),
        body.get("textXpMax", 25),
        body.get("textXpCooldown", 60),
        body.get("voiceXpPerMinute", 10),
        body.get("levelupChannelId"),
        body.get("levelupMessageEnabled", True),
    )

    return {
        "guildId": guild_id,
        "textXpMin": body.get("textXpMin", 15),
        "textXpMax": body.get("textXpMax", 25),
        "textXpCooldown": body.get("textXpCooldown", 60),
        "voiceXpPerMinute": body.get("voiceXpPerMinute", 10),
        "levelupChannelId": body.get("levelupChannelId"),
        "levelupMessageEnabled": body.get("levelupMessageEnabled", True),
    }


@router.get("/{guild_id}/leaderboard")
async def get_leaderboard_route(guild_id: str, request: Request, category: str = "text"):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()

    if category == "voice":
        rows = await pool.fetch(
            """
            SELECT user_id, voice_xp AS xp, voice_level AS level
            FROM member_xp
            WHERE guild_id = $1
            ORDER BY voice_xp DESC
            LIMIT 10
            """,
            guild_id,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT user_id, text_xp AS xp, text_level AS level
            FROM member_xp
            WHERE guild_id = $1
            ORDER BY text_xp DESC
            LIMIT 10
            """,
            guild_id,
        )

    import asyncio

    async def enrich(i: int, r):
        user = await _fetch_discord_user(r["user_id"])
        avatar_url = None
        if user and user.get("avatar"):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size=64"
        username = None
        display_name = None
        if user:
            username = user.get("username")
            display_name = user.get("global_name") or user.get("username")
        return {
            "userId": r["user_id"],
            "username": username,
            "displayName": display_name,
            "avatarUrl": avatar_url,
            "xp": r["xp"],
            "level": r["level"],
            "rank": i + 1,
        }

    return await asyncio.gather(*[enrich(i, r) for i, r in enumerate(rows)])


@router.get("/{guild_id}/dashboard-access")
async def list_dashboard_access_route(guild_id: str, request: Request):
    """
    Read-only view of who has been explicitly granted dashboard access
    (beyond Manage Server / Administrator). Managed via the bot's
    /dashboard-access command, not editable from the web dashboard.
    """
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT id, guild_id, target_type, target_id, added_by, created_at
        FROM dashboard_access
        WHERE guild_id = $1
        ORDER BY created_at ASC
        """,
        guild_id,
    )
    return [
        {
            "id": r["id"],
            "guildId": r["guild_id"],
            "targetType": r["target_type"],
            "targetId": r["target_id"],
            "addedBy": r["added_by"],
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.get("/{guild_id}/members/search")
async def search_guild_members(guild_id: str, request: Request, q: str = ""):
    """Search current guild members by username/nickname for the XP editor."""
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    if not q or len(q.strip()) < 1:
        return []

    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    async with aiohttp.ClientSession() as http:
        async with http.get(
            f"{DISCORD_API}/guilds/{guild_id}/members/search",
            headers={"Authorization": f"Bot {bot_token}"},
            params={"query": q.strip(), "limit": 10},
        ) as resp:
            if resp.status != 200:
                return []
            members = await resp.json()

    results = []
    for m in members:
        user = m.get("user") or {}
        avatar_url = None
        if user.get("avatar"):
            avatar_url = f"https://cdn.discordapp.com/avatars/{user['id']}/{user['avatar']}.png?size=64"
        results.append({
            "userId": user.get("id"),
            "username": user.get("username"),
            "displayName": m.get("nick") or user.get("global_name") or user.get("username"),
            "avatarUrl": avatar_url,
        })
    return results


@router.get("/{guild_id}/members/{user_id}/xp")
async def get_member_xp(guild_id: str, user_id: str, request: Request):
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM member_xp WHERE guild_id = $1 AND user_id = $2",
        guild_id,
        user_id,
    )
    if not row:
        return {
            "guildId": guild_id,
            "userId": user_id,
            "textXp": 0,
            "textLevel": 0,
            "voiceXp": 0,
            "voiceLevel": 0,
        }
    return {
        "guildId": guild_id,
        "userId": user_id,
        "textXp": row["text_xp"],
        "textLevel": row["text_level"],
        "voiceXp": row["voice_xp"],
        "voiceLevel": row["voice_level"],
    }


@router.put("/{guild_id}/members/{user_id}/xp")
async def update_member_xp(guild_id: str, user_id: str, request: Request):
    """Admin override: directly set a member's XP/level from the dashboard."""
    from web.core.database import get_pool
    session = _require_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    body = await request.json()
    text_xp = max(0, int(body.get("textXp", 0)))
    text_level = max(0, int(body.get("textLevel", 0)))
    voice_xp = max(0, int(body.get("voiceXp", 0)))
    voice_level = max(0, int(body.get("voiceLevel", 0)))

    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO member_xp (guild_id, user_id, text_xp, voice_xp, text_level, voice_level)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET
            text_xp     = EXCLUDED.text_xp,
            voice_xp    = EXCLUDED.voice_xp,
            text_level  = EXCLUDED.text_level,
            voice_level = EXCLUDED.voice_level
        """,
        guild_id,
        user_id,
        text_xp,
        voice_xp,
        text_level,
        voice_level,
    )

    return {
        "guildId": guild_id,
        "userId": user_id,
        "textXp": text_xp,
        "textLevel": text_level,
        "voiceXp": voice_xp,
        "voiceLevel": voice_level,
    }
