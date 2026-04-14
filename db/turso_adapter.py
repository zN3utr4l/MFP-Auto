"""Adapter that makes libsql-client look like aiosqlite for our CRUD functions.

Used when TURSO_DB_URL is set. Falls back to aiosqlite for local dev/tests.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class _Row:
    """Dict-like row that supports both row["col"] and row[index] access."""

    __slots__ = ("_columns", "_values")

    def __init__(self, columns: list[str], values: tuple) -> None:
        self._columns = columns
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._columns.index(key)]
        return self._values[key]

    def keys(self):
        return self._columns


class _Cursor:
    """Minimal cursor wrapping a libsql ResultSet."""

    def __init__(self, columns: list[str], rows: list[tuple], last_insert_rowid: int | None = None) -> None:
        self._columns = columns
        self._rows = rows
        self._pos = 0
        self.lastrowid = last_insert_rowid

    async def fetchone(self) -> _Row | None:
        if self._pos < len(self._rows):
            row = _Row(self._columns, self._rows[self._pos])
            self._pos += 1
            return row
        return None

    def __aiter__(self):
        return self

    async def __anext__(self) -> _Row:
        if self._pos < len(self._rows):
            row = _Row(self._columns, self._rows[self._pos])
            self._pos += 1
            return row
        raise StopAsyncIteration

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class TursoDb:
    """Async DB connection backed by Turso via libsql-client.

    Provides the subset of aiosqlite.Connection API that database.py uses:
    - execute(sql, params) → cursor
    - executescript(sql)
    - commit()
    - close()
    - async with db.execute(...) as cursor
    """

    def __init__(self, client) -> None:
        self._client = client

    async def execute(self, sql: str, params: tuple = ()) -> _Cursor:
        # libsql-client uses list params, not tuple
        rs = await self._client.execute(sql, list(params))
        columns = list(rs.columns) if rs.columns else []
        rows = [tuple(r) for r in rs.rows]
        return _Cursor(columns, rows, rs.last_insert_rowid)

    async def executescript(self, sql: str) -> None:
        """Execute multiple SQL statements separated by semicolons."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        for stmt in statements:
            await self._client.execute(stmt)

    async def commit(self) -> None:
        # Turso auto-commits each statement
        pass

    async def close(self) -> None:
        await self._client.close()


async def connect_turso(url: str, auth_token: str) -> TursoDb:
    """Create a TursoDb connection."""
    import libsql_client

    # libsql-client needs https:// URL for HTTP transport (not libsql:// which uses WebSocket)
    if url.startswith("libsql://"):
        url = url.replace("libsql://", "https://", 1)

    client = libsql_client.create_client(url=url, auth_token=auth_token)
    logger.info("Connected to Turso: %s", url.split("//")[1] if "//" in url else url)
    return TursoDb(client)
