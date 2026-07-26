import asyncpg
import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool(database_url: str) -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(database_url, min_size=1, max_size=10)
        logger.info("Database connection pool created")
        await _ensure_schema(_pool)
    return _pool


async def _ensure_schema(pool: asyncpg.Pool) -> None:
    """
    Idempotently applies any schema changes the bot depends on.
    Uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS so it is safe to run on
    every startup against both fresh and existing databases.
    """
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS guild_configs (
                guild_id             TEXT PRIMARY KEY,
                default_log_channel  TEXT,
                log_channels         JSONB NOT NULL DEFAULT '{}',
                creation_voice_channel TEXT,
                updated_at           TIMESTAMPTZ
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS log_entries (
                id          BIGSERIAL PRIMARY KEY,
                guild_id    TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                user_id     TEXT,
                target_id   TEXT,
                description TEXT NOT NULL,
                metadata    JSONB NOT NULL DEFAULT '{}',
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS member_events (
                id          BIGSERIAL PRIMARY KEY,
                guild_id    TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS message_stats (
                guild_id    TEXT NOT NULL,
                channel_id  TEXT NOT NULL,
                user_id     TEXT NOT NULL,
                is_bot      BOOLEAN NOT NULL DEFAULT FALSE,
                stat_date   DATE NOT NULL,
                count       INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, channel_id, user_id, stat_date)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS temp_voice_channels (
                channel_id  TEXT PRIMARY KEY,
                guild_id    TEXT NOT NULL,
                owner_id    TEXT NOT NULL,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Leveling system tables
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS member_xp (
                guild_id        TEXT NOT NULL,
                user_id         TEXT NOT NULL,
                text_xp         BIGINT NOT NULL DEFAULT 0,
                voice_xp        BIGINT NOT NULL DEFAULT 0,
                text_level      INTEGER NOT NULL DEFAULT 0,
                voice_level     INTEGER NOT NULL DEFAULT 0,
                last_message_at TIMESTAMPTZ,
                PRIMARY KEY (guild_id, user_id)
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS leveling_config (
                guild_id                TEXT PRIMARY KEY,
                text_xp_min             INTEGER NOT NULL DEFAULT 15,
                text_xp_max             INTEGER NOT NULL DEFAULT 25,
                text_xp_cooldown        INTEGER NOT NULL DEFAULT 60,
                voice_xp_per_minute     INTEGER NOT NULL DEFAULT 10,
                levelup_channel_id      TEXT,
                levelup_message_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """)

        # Dashboard access grants: lets the server owner/admins allow a
        # specific role or user to access the web dashboard for a guild,
        # without needing Discord's Manage Server / Administrator permission.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dashboard_access (
                id          BIGSERIAL PRIMARY KEY,
                guild_id    TEXT NOT NULL,
                target_type TEXT NOT NULL CHECK (target_type IN ('role', 'user')),
                target_id   TEXT NOT NULL,
                added_by    TEXT,
                created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (guild_id, target_type, target_id)
            )
        """)

        # Column additions for older databases
        await conn.execute("""
            ALTER TABLE guild_configs
                ADD COLUMN IF NOT EXISTS creation_voice_channel TEXT
        """)

    logger.info("Database schema verified / migrated successfully")


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard access helpers
# ──────────────────────────────────────────────────────────────────────────────

async def add_dashboard_access(
    pool: asyncpg.Pool,
    guild_id: str,
    target_type: str,
    target_id: str,
    added_by: str,
) -> bool:
    """Grant dashboard access to a role or user. Returns False if it already existed."""
    result = await pool.execute(
        """
        INSERT INTO dashboard_access (guild_id, target_type, target_id, added_by)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id, target_type, target_id) DO NOTHING
        """,
        guild_id,
        target_type,
        target_id,
        added_by,
    )
    return result.endswith("1")


async def remove_dashboard_access(
    pool: asyncpg.Pool,
    guild_id: str,
    target_type: str,
    target_id: str,
) -> bool:
    result = await pool.execute(
        """
        DELETE FROM dashboard_access
        WHERE guild_id = $1 AND target_type = $2 AND target_id = $3
        """,
        guild_id,
        target_type,
        target_id,
    )
    return result.endswith("1")


async def list_dashboard_access(pool: asyncpg.Pool, guild_id: str) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, guild_id, target_type, target_id, added_by, created_at
        FROM dashboard_access
        WHERE guild_id = $1
        ORDER BY created_at ASC
        """,
        guild_id,
    )
    return [dict(r) for r in rows]


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")


async def get_default_log_channel(pool: asyncpg.Pool, guild_id: str) -> Optional[str]:
    row = await pool.fetchrow(
        "SELECT default_log_channel FROM guild_configs WHERE guild_id = $1",
        guild_id,
    )
    return row["default_log_channel"] if row else None


async def get_log_channel(pool: asyncpg.Pool, guild_id: str, event_type: str) -> Optional[str]:
    row = await pool.fetchrow(
        """
        SELECT
            log_channels->$2 AS specific_channel,
            default_log_channel
        FROM guild_configs
        WHERE guild_id = $1
        """,
        guild_id,
        event_type,
    )
    if not row:
        return None

    specific = row["specific_channel"]
    if specific and specific.strip('"') and specific.strip('"') != "null":
        channel_id = specific.strip('"')
        return channel_id if channel_id else None

    default = row["default_log_channel"]
    return default if default else None


async def insert_log_entry(
    pool: asyncpg.Pool,
    guild_id: str,
    event_type: str,
    description: str,
    user_id: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    created_at=None,
) -> None:
    import json
    import datetime
    await pool.execute(
        """
        INSERT INTO log_entries (guild_id, event_type, user_id, target_id, description, metadata, created_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        guild_id,
        event_type,
        user_id,
        target_id,
        description,
        json.dumps(metadata or {}),
        created_at or datetime.datetime.now(datetime.timezone.utc),
    )


async def track_member_event(
    pool: asyncpg.Pool,
    guild_id: str,
    user_id: str,
    event_type: str,
) -> None:
    await pool.execute(
        """
        INSERT INTO member_events (guild_id, user_id, event_type, created_at)
        VALUES ($1, $2, $3, NOW())
        """,
        guild_id,
        user_id,
        event_type,
    )


async def track_message_event(
    pool: asyncpg.Pool,
    guild_id: str,
    channel_id: str,
    user_id: str,
    is_bot: bool,
) -> None:
    today = __import__("datetime").date.today()
    await pool.execute(
        """
        INSERT INTO message_stats (guild_id, channel_id, user_id, is_bot, stat_date, count)
        VALUES ($1, $2, $3, $4, $5, 1)
        ON CONFLICT (guild_id, channel_id, user_id, stat_date)
        DO UPDATE SET count = message_stats.count + 1
        """,
        guild_id,
        channel_id,
        user_id,
        is_bot,
        today,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Temp voice channel helpers
# ──────────────────────────────────────────────────────────────────────────────

async def get_creation_voice_channel(pool: asyncpg.Pool, guild_id: str) -> Optional[str]:
    row = await pool.fetchrow(
        "SELECT creation_voice_channel FROM guild_configs WHERE guild_id = $1",
        guild_id,
    )
    return row["creation_voice_channel"] if row else None


async def add_temp_channel(
    pool: asyncpg.Pool,
    channel_id: str,
    guild_id: str,
    owner_id: str,
) -> None:
    await pool.execute(
        """
        INSERT INTO temp_voice_channels (channel_id, guild_id, owner_id, created_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (channel_id) DO NOTHING
        """,
        channel_id,
        guild_id,
        owner_id,
    )


async def remove_temp_channel(pool: asyncpg.Pool, channel_id: str) -> None:
    await pool.execute(
        "DELETE FROM temp_voice_channels WHERE channel_id = $1",
        channel_id,
    )


async def is_temp_channel(pool: asyncpg.Pool, channel_id: str) -> bool:
    row = await pool.fetchrow(
        "SELECT 1 FROM temp_voice_channels WHERE channel_id = $1",
        channel_id,
    )
    return row is not None


async def get_temp_channel_owner(pool: asyncpg.Pool, channel_id: str) -> Optional[str]:
    row = await pool.fetchrow(
        "SELECT owner_id FROM temp_voice_channels WHERE channel_id = $1",
        channel_id,
    )
    return row["owner_id"] if row else None


async def get_all_temp_channels(pool: asyncpg.Pool) -> list[dict]:
    rows = await pool.fetch("SELECT channel_id, guild_id, owner_id FROM temp_voice_channels")
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# Leveling helpers
# ──────────────────────────────────────────────────────────────────────────────

def xp_for_level(level: int) -> int:
    """Total XP required to reach a given level from 0."""
    return 100 * level * (level + 1) // 2


def level_from_xp(xp: int) -> int:
    """Compute level from total XP using quadratic formula."""
    if xp <= 0:
        return 0
    return int((-1 + math.sqrt(1 + 8 * xp / 100)) / 2)


async def get_leveling_config(pool: asyncpg.Pool, guild_id: str) -> dict:
    row = await pool.fetchrow(
        "SELECT * FROM leveling_config WHERE guild_id = $1",
        guild_id,
    )
    if row:
        return dict(row)
    return {
        "guild_id": guild_id,
        "text_xp_min": 15,
        "text_xp_max": 25,
        "text_xp_cooldown": 60,
        "voice_xp_per_minute": 10,
        "levelup_channel_id": None,
        "levelup_message_enabled": True,
    }


async def upsert_leveling_config(pool: asyncpg.Pool, guild_id: str, **kwargs) -> dict:
    config = await get_leveling_config(pool, guild_id)
    config.update(kwargs)
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
        config["text_xp_min"],
        config["text_xp_max"],
        config["text_xp_cooldown"],
        config["voice_xp_per_minute"],
        config.get("levelup_channel_id"),
        config["levelup_message_enabled"],
    )
    return config


async def add_text_xp(
    pool: asyncpg.Pool,
    guild_id: str,
    user_id: str,
    xp: int,
    cooldown_seconds: int,
) -> Optional[dict]:
    """
    Award text XP to a user respecting cooldown.
    Returns a dict with old_level and new_level if XP was awarded, else None.
    """
    import json
    row = await pool.fetchrow(
        """
        SELECT text_xp, text_level, last_message_at
        FROM member_xp
        WHERE guild_id = $1 AND user_id = $2
        """,
        guild_id,
        user_id,
    )

    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)

    if row:
        if row["last_message_at"]:
            elapsed = (now - row["last_message_at"]).total_seconds()
            if elapsed < cooldown_seconds:
                return None
        old_xp = row["text_xp"]
        old_level = row["text_level"]
    else:
        old_xp = 0
        old_level = 0

    new_xp = old_xp + xp
    new_level = level_from_xp(new_xp)

    await pool.execute(
        """
        INSERT INTO member_xp (guild_id, user_id, text_xp, text_level, last_message_at)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET
            text_xp = EXCLUDED.text_xp,
            text_level = EXCLUDED.text_level,
            last_message_at = EXCLUDED.last_message_at
        """,
        guild_id,
        user_id,
        new_xp,
        new_level,
        now,
    )

    return {"old_level": old_level, "new_level": new_level, "xp": new_xp}


async def add_voice_xp(
    pool: asyncpg.Pool,
    guild_id: str,
    user_id: str,
    xp: int,
) -> Optional[dict]:
    """
    Award voice XP to a user.
    Returns dict with old_level and new_level.
    """
    row = await pool.fetchrow(
        "SELECT voice_xp, voice_level FROM member_xp WHERE guild_id = $1 AND user_id = $2",
        guild_id,
        user_id,
    )
    old_xp = row["voice_xp"] if row else 0
    old_level = row["voice_level"] if row else 0
    new_xp = old_xp + xp
    new_level = level_from_xp(new_xp)

    await pool.execute(
        """
        INSERT INTO member_xp (guild_id, user_id, voice_xp, voice_level)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (guild_id, user_id) DO UPDATE SET
            voice_xp = EXCLUDED.voice_xp,
            voice_level = EXCLUDED.voice_level
        """,
        guild_id,
        user_id,
        new_xp,
        new_level,
    )
    return {"old_level": old_level, "new_level": new_level, "xp": new_xp}


async def get_user_xp(pool: asyncpg.Pool, guild_id: str, user_id: str) -> dict:
    row = await pool.fetchrow(
        "SELECT text_xp, voice_xp, text_level, voice_level FROM member_xp WHERE guild_id = $1 AND user_id = $2",
        guild_id,
        user_id,
    )
    if row:
        return dict(row)
    return {"text_xp": 0, "voice_xp": 0, "text_level": 0, "voice_level": 0}


async def get_text_leaderboard(pool: asyncpg.Pool, guild_id: str, limit: int = 10) -> list:
    rows = await pool.fetch(
        """
        SELECT user_id, text_xp, text_level
        FROM member_xp
        WHERE guild_id = $1
        ORDER BY text_xp DESC
        LIMIT $2
        """,
        guild_id,
        limit,
    )
    return [dict(r) for r in rows]


async def get_voice_leaderboard(pool: asyncpg.Pool, guild_id: str, limit: int = 10) -> list:
    rows = await pool.fetch(
        """
        SELECT user_id, voice_xp, voice_level
        FROM member_xp
        WHERE guild_id = $1
        ORDER BY voice_xp DESC
        LIMIT $2
        """,
        guild_id,
        limit,
    )
    return [dict(r) for r in rows]


async def get_user_text_rank(pool: asyncpg.Pool, guild_id: str, user_id: str) -> int:
    row = await pool.fetchrow(
        """
        SELECT COUNT(*) + 1 AS rank
        FROM member_xp
        WHERE guild_id = $1
          AND text_xp > (SELECT COALESCE(text_xp, 0) FROM member_xp WHERE guild_id = $1 AND user_id = $2)
        """,
        guild_id,
        user_id,
    )
    return row["rank"] if row else 1


async def get_user_voice_rank(pool: asyncpg.Pool, guild_id: str, user_id: str) -> int:
    row = await pool.fetchrow(
        """
        SELECT COUNT(*) + 1 AS rank
        FROM member_xp
        WHERE guild_id = $1
          AND voice_xp > (SELECT COALESCE(voice_xp, 0) FROM member_xp WHERE guild_id = $1 AND user_id = $2)
        """,
        guild_id,
        user_id,
    )
    return row["rank"] if row else 1
