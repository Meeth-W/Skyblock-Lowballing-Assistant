"""SQLite connection management.

WAL mode so the asyncio thread can write while the GUI thread
reads.  Autocommit at the driver level with explicit transactions in the event
store, so a projection update and the event that caused it commit together or
not at all.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
PROJECTIONS_PATH = Path(__file__).with_name("projections.sql")


def connect(path: str | Path = ":memory:") -> sqlite3.Connection:
    """Open a connection with the pragmas this app depends on."""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def split_statements(sql: str) -> list[str]:
    """Split a schema file into individual statements.

    ``executescript`` would be simpler, but it issues an implicit COMMIT first,
    which would silently end the transaction a rebuild runs inside.  These
    schema files contain no semicolons outside statement terminators, so a
    comment-stripped split is exact.
    """
    without_comments = re.sub("--.*", "", sql)
    return [s.strip() for s in without_comments.split(";") if s.strip()]


def exec_script(conn: sqlite3.Connection, sql: str) -> None:
    """Run a schema file without disturbing the surrounding transaction."""
    for statement in split_statements(sql):
        conn.execute(statement)


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the durable tables.  Safe to call on an existing database."""
    exec_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))


def apply_projections(conn: sqlite3.Connection) -> None:
    """Drop and recreate every derived table.  Always followed by a replay."""
    exec_script(conn, PROJECTIONS_PATH.read_text(encoding="utf-8"))


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Explicit transaction.  A nested call joins the outer one."""
    if conn.in_transaction:
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r["name"] for r in rows}
