import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "scrim.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS scrims (
    scrim_id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER,
    creator_id INTEGER NOT NULL,
    capacity INTEGER NOT NULL DEFAULT 10,
    status TEXT NOT NULL DEFAULT 'open',
    auto_close_done INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scrim_participants (
    scrim_id INTEGER NOT NULL,
    discord_user_id INTEGER NOT NULL,
    is_waitlist INTEGER NOT NULL DEFAULT 0,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scrim_id, discord_user_id),
    FOREIGN KEY (scrim_id) REFERENCES scrims(scrim_id)
);

CREATE TABLE IF NOT EXISTS scrim_proxy_participants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scrim_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    tier_raw TEXT NOT NULL,
    positions TEXT NOT NULL,
    proxy_by_user_id INTEGER NOT NULL,
    is_waitlist INTEGER NOT NULL DEFAULT 0,
    joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (scrim_id, name),
    FOREIGN KEY (scrim_id) REFERENCES scrims(scrim_id)
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(scrim_participants)")}
        if "is_waitlist" not in cols:
            conn.execute(
                "ALTER TABLE scrim_participants ADD COLUMN is_waitlist INTEGER NOT NULL DEFAULT 0"
            )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(scrims)")}
        if "auto_close_done" not in cols:
            conn.execute(
                "ALTER TABLE scrims ADD COLUMN auto_close_done INTEGER NOT NULL DEFAULT 0"
            )


def create_scrim(guild_id: int, channel_id: int, creator_id: int, capacity: int = 10) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO scrims (guild_id, channel_id, creator_id, capacity) VALUES (?, ?, ?, ?)",
            (guild_id, channel_id, creator_id, capacity),
        )
        return cur.lastrowid


def set_message_id(scrim_id: int, message_id: int) -> None:
    with connect() as conn:
        conn.execute("UPDATE scrims SET message_id = ? WHERE scrim_id = ?", (message_id, scrim_id))


def get_scrim(scrim_id: int) -> sqlite3.Row | None:
    with connect() as conn:
        return conn.execute("SELECT * FROM scrims WHERE scrim_id = ?", (scrim_id,)).fetchone()


def mark_summary_sent(scrim_id: int) -> None:
    """정원 도달 시 정리 임베드를 1회만 보내기 위한 플래그."""
    with connect() as conn:
        conn.execute(
            "UPDATE scrims SET auto_close_done = 1 WHERE scrim_id = ?", (scrim_id,)
        )


def add_participant(scrim_id: int, user_id: int, is_waitlist: bool = False) -> bool:
    """Returns True if added, False if duplicate."""
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO scrim_participants (scrim_id, discord_user_id, is_waitlist) "
                "VALUES (?, ?, ?)",
                (scrim_id, user_id, 1 if is_waitlist else 0),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def remove_participant(scrim_id: int, user_id: int) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM scrim_participants WHERE scrim_id = ? AND discord_user_id = ?",
            (scrim_id, user_id),
        )
        return cur.rowcount > 0


def get_participants(scrim_id: int) -> list[tuple[int, int]]:
    """Returns [(user_id, is_waitlist), ...] main first then waitlist, each in join order."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT discord_user_id, is_waitlist FROM scrim_participants "
            "WHERE scrim_id = ? ORDER BY is_waitlist ASC, joined_at ASC",
            (scrim_id,),
        ).fetchall()
        return [(r["discord_user_id"], r["is_waitlist"]) for r in rows]


def promote_oldest_waitlist(scrim_id: int) -> dict | None:
    """대기자 중 가장 먼저 등록된 사람(본인 or 대리)을 정참가자로 승격.

    Returns:
        {'type': 'own', 'user_id': int}
        {'type': 'proxy', 'name': str, 'proxy_by_user_id': int}
        None (대기자 없을 때)
    """
    with connect() as conn:
        own = conn.execute(
            "SELECT discord_user_id, joined_at FROM scrim_participants "
            "WHERE scrim_id = ? AND is_waitlist = 1 ORDER BY joined_at ASC LIMIT 1",
            (scrim_id,),
        ).fetchone()
        proxy = conn.execute(
            "SELECT name, proxy_by_user_id, joined_at FROM scrim_proxy_participants "
            "WHERE scrim_id = ? AND is_waitlist = 1 ORDER BY joined_at ASC LIMIT 1",
            (scrim_id,),
        ).fetchone()

        if own is None and proxy is None:
            return None
        if proxy is None or (own is not None and own["joined_at"] <= proxy["joined_at"]):
            conn.execute(
                "UPDATE scrim_participants SET is_waitlist = 0 "
                "WHERE scrim_id = ? AND discord_user_id = ?",
                (scrim_id, own["discord_user_id"]),
            )
            return {"type": "own", "user_id": own["discord_user_id"]}
        conn.execute(
            "UPDATE scrim_proxy_participants SET is_waitlist = 0 "
            "WHERE scrim_id = ? AND name = ?",
            (scrim_id, proxy["name"]),
        )
        return {"type": "proxy", "name": proxy["name"], "proxy_by_user_id": proxy["proxy_by_user_id"]}


def add_proxy_participant(
    scrim_id: int,
    name: str,
    tier_raw: str,
    positions: str,
    proxy_by_user_id: int,
    is_waitlist: bool = False,
) -> bool:
    """대리 참가자 등록. 같은 scrim 내 동일 이름은 거부."""
    with connect() as conn:
        try:
            conn.execute(
                "INSERT INTO scrim_proxy_participants "
                "(scrim_id, name, tier_raw, positions, proxy_by_user_id, is_waitlist) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (scrim_id, name, tier_raw, positions, proxy_by_user_id, 1 if is_waitlist else 0),
            )
            return True
        except sqlite3.IntegrityError:
            return False


def get_proxy_participants(scrim_id: int) -> list[dict]:
    """대리 참가자 전체 (main 먼저, 각각 joined_at 순)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT name, tier_raw, positions, proxy_by_user_id, is_waitlist "
            "FROM scrim_proxy_participants "
            "WHERE scrim_id = ? ORDER BY is_waitlist ASC, joined_at ASC",
            (scrim_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def remove_proxy_participant(scrim_id: int, name: str) -> bool:
    with connect() as conn:
        cur = conn.execute(
            "DELETE FROM scrim_proxy_participants WHERE scrim_id = ? AND name = ?",
            (scrim_id, name),
        )
        return cur.rowcount > 0


def find_latest_open_scrim_in_channel(channel_id: int) -> sqlite3.Row | None:
    """채널 내 가장 최근 모집 (대신참가 커맨드에서 사용)."""
    with connect() as conn:
        return conn.execute(
            "SELECT * FROM scrims WHERE channel_id = ? "
            "ORDER BY scrim_id DESC LIMIT 1",
            (channel_id,),
        ).fetchone()


def get_persistent_scrims() -> list[sqlite3.Row]:
    """Open + recently closed scrims (last 30 days) for view restoration."""
    with connect() as conn:
        return list(
            conn.execute(
                "SELECT scrim_id, message_id, status "
                "FROM scrims "
                "WHERE message_id IS NOT NULL "
                "  AND created_at > datetime('now', '-30 days')"
            )
        )
