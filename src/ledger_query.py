from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

from .models import LedgerFilters


class LedgerQueryError(Exception):
    """Raised when a SQLite execution error occurs in LedgerQueryEngine."""


class LedgerQueryEngine:
    def __init__(self, db_path: Path) -> None:
        if not db_path.exists():
            raise FileNotFoundError(f"Database file not found: {db_path}")
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def _validate_filters(self, filters: LedgerFilters) -> None:
        """Validate filter types before SQL execution."""
        if filters.date_from is not None and not isinstance(filters.date_from, str):
            raise ValueError(f"date_from must be a string or None, got {type(filters.date_from)}")
        if filters.date_to is not None and not isinstance(filters.date_to, str):
            raise ValueError(f"date_to must be a string or None, got {type(filters.date_to)}")
        if filters.amount_min is not None and not isinstance(filters.amount_min, (float, int)):
            raise ValueError(f"amount_min must be float/int or None, got {type(filters.amount_min)}")
        if filters.amount_max is not None and not isinstance(filters.amount_max, (float, int)):
            raise ValueError(f"amount_max must be float/int or None, got {type(filters.amount_max)}")

    def _build_query(self, filters: LedgerFilters, table: str = "transactions") -> tuple[str, list]:
        """Build a parameterized SQL query with WHERE clauses using ? placeholders only."""
        clauses: list[str] = []
        params: list = []

        # Determine if this is a sub_ledger table (uses 'amount') or ledger (uses debit+credit)
        is_sub_ledger = table == "sub_ledger"

        if filters.date_from is not None:
            clauses.append("date >= ?")
            params.append(filters.date_from)

        if filters.date_to is not None:
            clauses.append("date <= ?")
            params.append(filters.date_to)

        if filters.amount_min is not None:
            if is_sub_ledger:
                clauses.append("amount >= ?")
            else:
                clauses.append("(debit + credit) >= ?")
            params.append(filters.amount_min)

        if filters.amount_max is not None:
            if is_sub_ledger:
                clauses.append("amount <= ?")
            else:
                clauses.append("(debit + credit) <= ?")
            params.append(filters.amount_max)

        if filters.account_code is not None:
            clauses.append("account = ?")
            params.append(filters.account_code)

        if filters.vendor_id is not None:
            clauses.append("vendor = ?")
            params.append(filters.vendor_id)

        sql = f"SELECT * FROM {table}"  # table name is internal, not user-supplied
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)

        return sql, params

    def query(self, filters: LedgerFilters, table: str = "transactions", limit: int = 50) -> list[dict]:
        """Execute a parameterized query and return results as a list of dicts."""
        self._validate_filters(filters)
        sql, params = self._build_query(filters, table)
        sql += " LIMIT ?"
        params.append(limit)

        try:
            cursor = self._conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            raise LedgerQueryError(str(e)) from e

    def close(self) -> None:
        """Close the SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "LedgerQueryEngine":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
