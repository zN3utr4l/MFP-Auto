"""Adapter that makes Turso HTTP API look like aiosqlite for our CRUD functions.

Uses Turso's HTTP pipeline API directly instead of libsql-client
(which has bugs with HTTP transport).
"""

from __future__ import annotations

import json
import logging

import aiohttp

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
    """Minimal cursor wrapping query results."""

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


class _ExecuteProxy:
    """Wraps execute() so it works as both `await db.execute(...)` and `async with db.execute(...) as cursor:`."""

    def __init__(self, coro):
        self._coro = coro

    def __await__(self):
        return self._coro.__await__()

    async def __aenter__(self):
        return await self._coro

    async def __aexit__(self, *args):
        pass


class TursoDb:
    """Async DB connection using Turso HTTP API directly."""

    def __init__(self, base_url: str, auth_token: str) -> None:
        self._url = f"{base_url}/v2/pipeline"
        self._headers = {
            "Authorization": f"Bearer {auth_token}",
            "Content-Type": "application/json",
        }
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _raw_execute(self, sql: str, params: list) -> dict:
        """Execute a single SQL statement via Turso HTTP pipeline API."""
        # Convert Python values to Turso's typed args format
        args = []
        for p in params:
            if p is None:
                args.append({"type": "null", "value": None})
            elif isinstance(p, int):
                args.append({"type": "integer", "value": str(p)})
            elif isinstance(p, float):
                args.append({"type": "float", "value": p})
            else:
                args.append({"type": "text", "value": str(p)})

        body = {
            "requests": [
                {"type": "execute", "stmt": {"sql": sql, "args": args}},
                {"type": "close"},
            ]
        }

        session = await self._get_session()
        async with session.post(self._url, headers=self._headers, json=body) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Turso HTTP {resp.status}: {text[:300]}")
            data = await resp.json()

        results = data.get("results", [])
        if not results:
            raise RuntimeError(f"Turso: empty results for: {sql[:100]}")

        first = results[0]
        if first.get("type") == "error":
            err = first.get("error", {})
            raise RuntimeError(f"Turso SQL error: {err.get('message', str(err))}")

        response = first.get("response", {}).get("result", {})
        return response

    def execute(self, sql: str, params: tuple = ()) -> _ExecuteProxy:
        return _ExecuteProxy(self._do_execute(sql, params))

    async def _do_execute(self, sql: str, params: tuple) -> _Cursor:
        result = await self._raw_execute(sql, list(params))
        cols = [c.get("name", "") for c in result.get("cols", [])]
        rows_raw = result.get("rows", [])
        rows = []
        for r in rows_raw:
            row = tuple(cell.get("value") for cell in r)
            rows.append(row)
        last_id = result.get("last_insert_rowid")
        return _Cursor(cols, rows, int(last_id) if last_id is not None else None)

    async def executescript(self, sql: str) -> None:
        """Execute multiple SQL statements via pipeline."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]

        requests = []
        for stmt in statements:
            requests.append({"type": "execute", "stmt": {"sql": stmt}})
        requests.append({"type": "close"})

        body = {"requests": requests}
        session = await self._get_session()
        async with session.post(self._url, headers=self._headers, json=body) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Turso HTTP {resp.status}: {text[:300]}")
            data = await resp.json()

        for i, result in enumerate(data.get("results", [])):
            if result.get("type") == "error":
                err = result.get("error", {})
                logger.error("Turso executescript error at stmt %d: %s", i, err.get("message", str(err)))
                raise RuntimeError(f"Turso SQL error: {err.get('message', str(err))}")

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


async def connect_turso(url: str, auth_token: str) -> TursoDb:
    """Create a TursoDb connection."""
    if url.startswith("libsql://"):
        url = url.replace("libsql://", "https://", 1)

    db = TursoDb(url, auth_token)
    # Test connection
    await db._raw_execute("SELECT 1", [])
    logger.info("Connected to Turso: %s", url.split("//")[1] if "//" in url else url)
    return db
