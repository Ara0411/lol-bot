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


def promote_oldest_waitlist(scrim_id: int) -> int | None:
    """If any waitlist member exists, promote the oldest to main. Returns user_id or None."""
    with connect() as conn:
        row = conn.execute(
            "SELECT discord_user_id FROM scrim_participants "
            "WHERE scrim_id = ? AND is_waitlist = 1 ORDER BY joined_at ASC LIMIT 1",
            (scrim_id,),
        ).fetchone()
        if row is None:
            return None
        uid = row["discord_user_id"]
        conn.execute(
            "UPDATE scrim_participants SET is_waitlist = 0 "
            "WHERE scrim_id = ? AND discord_user_id = ?",
            (scrim_id, uid),
        )
        return uid


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
