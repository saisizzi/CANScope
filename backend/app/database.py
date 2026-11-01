from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parents[1] / "data" / "canscope.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS frames (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                can_id INTEGER NOT NULL,
                sender TEXT NOT NULL,
                dlc INTEGER NOT NULL,
                payload_hex TEXT NOT NULL,
                decoded TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                severity TEXT NOT NULL,
                kind TEXT NOT NULL,
                message TEXT NOT NULL,
                can_id INTEGER,
                details TEXT NOT NULL DEFAULT '{}'
            )
            """
        )
        conn.commit()


def record_frame(frame: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO frames (timestamp, can_id, sender, dlc, payload_hex, decoded)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                frame["timestamp"],
                frame["can_id"],
                frame["sender"],
                frame["dlc"],
                frame["payload_hex"],
                json.dumps(frame.get("decoded", {}), separators=(",", ":")),
            ),
        )
        conn.commit()


def record_event(event: dict[str, Any]) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO events (timestamp, severity, kind, message, can_id, details)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event["timestamp"],
                event["severity"],
                event["kind"],
                event["message"],
                event.get("can_id"),
                json.dumps(event.get("details", {}), separators=(",", ":")),
            ),
        )
        conn.commit()
