from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite


@dataclass(slots=True)
class Giveaway:
    id: int
    guild_id: int
    channel_id: int
    message_id: int | None
    host_id: int
    prize: str
    description: str
    winner_count: int
    ends_at: int
    status: str
    manual_winner_id: int | None
    manual_winner_ids: list[int]
    winners: list[int]
    created_at: int
    ended_at: int | None


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def connect(self) -> aiosqlite.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        return aiosqlite.connect(self.path)

    async def initialize(self) -> None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            await db.execute("PRAGMA journal_mode = WAL")
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER UNIQUE,
                    host_id INTEGER NOT NULL,
                    prize TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    winner_count INTEGER NOT NULL CHECK(winner_count BETWEEN 1 AND 20),
                    ends_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','ended')),
                    manual_winner_id INTEGER,
                    manual_winners_json TEXT NOT NULL DEFAULT '[]',
                    winners_json TEXT NOT NULL DEFAULT '[]',
                    created_at INTEGER NOT NULL,
                    ended_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS entries (
                    giveaway_id INTEGER NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
                    user_id INTEGER NOT NULL,
                    entered_at INTEGER NOT NULL,
                    PRIMARY KEY (giveaway_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    giveaway_id INTEGER NOT NULL REFERENCES giveaways(id) ON DELETE CASCADE,
                    actor_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT NOT NULL DEFAULT '',
                    created_at INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_due ON giveaways(status, ends_at);
                CREATE INDEX IF NOT EXISTS idx_guild_status ON giveaways(guild_id, status);
            """)
            columns = {row[1] for row in await (await db.execute("PRAGMA table_info(giveaways)")).fetchall()}
            if "manual_winners_json" not in columns:
                await db.execute("ALTER TABLE giveaways ADD COLUMN manual_winners_json TEXT NOT NULL DEFAULT '[]'")
                await db.execute(
                    "UPDATE giveaways SET manual_winners_json=json_array(manual_winner_id) WHERE manual_winner_id IS NOT NULL"
                )
            await db.commit()

    @staticmethod
    def _row(row: aiosqlite.Row | None) -> Giveaway | None:
        if row is None:
            return None
        data = dict(row)
        data["winners"] = json.loads(data.pop("winners_json"))
        manual_json = data.pop("manual_winners_json", "[]")
        data["manual_winner_ids"] = json.loads(manual_json)
        if not data["manual_winner_ids"] and data.get("manual_winner_id") is not None:
            data["manual_winner_ids"] = [data["manual_winner_id"]]
        return Giveaway(**data)

    async def create_giveaway(self, **values: Any) -> int:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("""
                INSERT INTO giveaways
                (guild_id, channel_id, host_id, prize, description, winner_count, ends_at, created_at)
                VALUES (:guild_id, :channel_id, :host_id, :prize, :description,
                        :winner_count, :ends_at, :created_at)
            """, values)
            await db.commit()
            return int(cur.lastrowid)

    async def set_message_id(self, giveaway_id: int, message_id: int) -> None:
        await self._execute("UPDATE giveaways SET message_id=? WHERE id=?", (message_id, giveaway_id))

    async def get(self, giveaway_id: int) -> Giveaway | None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM giveaways WHERE id=?", (giveaway_id,))
            return self._row(await cur.fetchone())

    async def get_by_message(self, message_id: int) -> Giveaway | None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM giveaways WHERE message_id=?", (message_id,))
            return self._row(await cur.fetchone())

    async def find_active_for_message_recovery(
        self, guild_id: int, channel_id: int, prize: str, now: int
    ) -> Giveaway | None:
        """Find the most likely stored giveaway when a Discord message lost its mapping."""
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT * FROM giveaways
                WHERE guild_id=? AND channel_id=? AND prize=?
                  AND status='active' AND ends_at>?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (guild_id, channel_id, prize, now),
            )
            return self._row(await cur.fetchone())

    async def list_dashboard(self, guild_id: int) -> list[Giveaway]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM giveaways WHERE guild_id=? ORDER BY status ASC, created_at DESC LIMIT 25",
                (guild_id,),
            )
            return [self._row(r) for r in await cur.fetchall()]  # type: ignore[misc]

    async def list_active(self, guild_id: int | None = None) -> list[Giveaway]:
        sql, params = "SELECT * FROM giveaways WHERE status='active'", ()
        if guild_id is not None:
            sql += " AND guild_id=?"
            params = (guild_id,)
        sql += " ORDER BY ends_at LIMIT 25"
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            return [self._row(r) for r in await cur.fetchall()]  # type: ignore[misc]

    async def due(self, now: int) -> list[Giveaway]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM giveaways WHERE status='active' AND ends_at<=? ORDER BY ends_at", (now,)
            )
            return [self._row(r) for r in await cur.fetchall()]  # type: ignore[misc]

    async def toggle_entry(self, giveaway_id: int, user_id: int, now: int) -> tuple[bool, int]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT status, ends_at FROM giveaways WHERE id=?", (giveaway_id,))
            row = await cur.fetchone()
            if row is None or row["status"] != "active" or int(row["ends_at"]) <= now:
                await db.rollback()
                raise ValueError("This giveaway has ended or no longer exists.")
            cur = await db.execute(
                "SELECT 1 FROM entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, user_id)
            )
            if await cur.fetchone():
                await db.execute("DELETE FROM entries WHERE giveaway_id=? AND user_id=?", (giveaway_id, user_id))
                joined = False
            else:
                await db.execute(
                    "INSERT INTO entries(giveaway_id,user_id,entered_at) VALUES(?,?,?)",
                    (giveaway_id, user_id, now),
                )
                joined = True
            cur = await db.execute("SELECT COUNT(*) FROM entries WHERE giveaway_id=?", (giveaway_id,))
            count = int((await cur.fetchone())[0])
            await db.commit()
            return joined, count

    async def entries(self, giveaway_id: int) -> list[int]:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT user_id FROM entries WHERE giveaway_id=? ORDER BY entered_at,user_id", (giveaway_id,)
            )
            return [int(r[0]) for r in await cur.fetchall()]

    async def entry_count(self, giveaway_id: int) -> int:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT COUNT(*) FROM entries WHERE giveaway_id=?", (giveaway_id,))
            return int((await cur.fetchone())[0])

    async def finish(self, giveaway_id: int, winners: list[int], ended_at: int) -> bool:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "UPDATE giveaways SET status='ended', winners_json=?, ended_at=? WHERE id=? AND status='active'",
                (json.dumps(winners), ended_at, giveaway_id),
            )
            await db.commit()
            return cur.rowcount == 1

    async def replace_winners(self, giveaway_id: int, winners: list[int], ended_at: int) -> None:
        await self._execute(
            "UPDATE giveaways SET winners_json=?, ended_at=? WHERE id=? AND status='ended'",
            (json.dumps(winners), ended_at, giveaway_id),
        )

    async def set_manual_winner(self, giveaway_id: int, user_id: int | None) -> None:
        await self.set_manual_winners(giveaway_id, [user_id] if user_id is not None else [])

    async def set_manual_winners(self, giveaway_id: int, user_ids: list[int]) -> None:
        unique = list(dict.fromkeys(user_ids))
        await self._execute(
            "UPDATE giveaways SET manual_winner_id=?, manual_winners_json=? WHERE id=? AND status='active'",
            (unique[0] if unique else None, json.dumps(unique), giveaway_id),
        )

    async def audit(self, giveaway_id: int, actor_id: int, action: str, detail: str, now: int) -> None:
        await self._execute(
            "INSERT INTO audit_log(giveaway_id,actor_id,action,detail,created_at) VALUES(?,?,?,?,?)",
            (giveaway_id, actor_id, action, detail, now),
        )

    async def _execute(self, sql: str, params: tuple[Any, ...]) -> None:
        async with self.connect() as db:
            db.row_factory = aiosqlite.Row
            await db.execute(sql, params)
            await db.commit()

