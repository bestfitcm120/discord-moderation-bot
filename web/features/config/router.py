import json
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

from web.core.database import get_pool
from web.core.session import get_session
from web.features.guilds.router import _user_can_access_guild

router = APIRouter()


@router.get("/{guild_id}/config")
async def get_guild_config(guild_id: str, request: Request):
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM guild_configs WHERE guild_id = $1",
        guild_id,
    )

    if not row:
        return {
            "guildId": guild_id,
            "defaultLogChannel": None,
            "logChannels": {},
            "updatedAt": None,
        }

    log_channels = row["log_channels"]
    if isinstance(log_channels, str):
        log_channels = json.loads(log_channels)

    return {
        "guildId": row["guild_id"],
        "defaultLogChannel": row["default_log_channel"],
        "logChannels": log_channels or {},
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None,
    }


@router.put("/{guild_id}/config")
async def update_guild_config(guild_id: str, request: Request):
    session = get_session(request)
    if not session:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    if not await _user_can_access_guild(guild_id, session):
        return JSONResponse({"error": "Forbidden"}, status_code=403)

    body = await request.json()
    default_log_channel = body.get("defaultLogChannel")
    log_channels = body.get("logChannels", {})

    pool = get_pool()
    now = datetime.now(timezone.utc)

    await pool.execute(
        """
        INSERT INTO guild_configs (guild_id, default_log_channel, log_channels, updated_at)
        VALUES ($1, $2, $3::jsonb, $4)
        ON CONFLICT (guild_id) DO UPDATE
            SET default_log_channel = EXCLUDED.default_log_channel,
                log_channels        = EXCLUDED.log_channels,
                updated_at          = EXCLUDED.updated_at
        """,
        guild_id,
        default_log_channel,
        json.dumps(log_channels),
        now,
    )

    return {
        "guildId": guild_id,
        "defaultLogChannel": default_log_channel,
        "logChannels": log_channels,
        "updatedAt": now.isoformat(),
    }
