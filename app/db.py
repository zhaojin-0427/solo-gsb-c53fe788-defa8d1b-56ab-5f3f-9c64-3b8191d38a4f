"""SQLite 持久化层：场景与对应的求解方案。"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", os.path.join("data", "app.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS scenarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    nodes      TEXT NOT NULL,
    edges      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS solutions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    scenario_id       INTEGER NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    repair_edge_id    TEXT NOT NULL,
    must_supply       TEXT NOT NULL,
    status            TEXT NOT NULL,
    closed_valves     TEXT NOT NULL,
    supplied          TEXT NOT NULL,
    unsupplied        TEXT NOT NULL,
    outage_households INTEGER NOT NULL,
    valve_count       INTEGER NOT NULL,
    solve_time_ms     INTEGER NOT NULL,
    message           TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_solutions_scenario ON solutions(scenario_id, id DESC);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def _conn():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript(SCHEMA)


def _scenario_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "nodes": json.loads(row["nodes"]),
        "edges": json.loads(row["edges"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _solution_from_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "scenario_id": row["scenario_id"],
        "repair_edge_id": row["repair_edge_id"],
        "must_supply": json.loads(row["must_supply"]),
        "status": row["status"],
        "closed_valves": json.loads(row["closed_valves"]),
        "supplied": json.loads(row["supplied"]),
        "unsupplied": json.loads(row["unsupplied"]),
        "outage_households": row["outage_households"],
        "valve_count": row["valve_count"],
        "solve_time_ms": row["solve_time_ms"],
        "message": row["message"],
        "created_at": row["created_at"],
    }


def list_scenarios() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT s.id, s.name, s.nodes, s.edges, s.updated_at,
                   EXISTS(SELECT 1 FROM solutions sol WHERE sol.scenario_id = s.id) AS has_solution
            FROM scenarios s ORDER BY s.id
            """
        ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "node_count": len(json.loads(r["nodes"])),
            "edge_count": len(json.loads(r["edges"])),
            "has_solution": bool(r["has_solution"]),
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def create_scenario(name: str, nodes: list[dict], edges: list[dict]) -> int:
    now = _now()
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO scenarios(name, nodes, edges, created_at, updated_at) VALUES (?,?,?,?,?)",
            (name, json.dumps(nodes), json.dumps(edges), now, now),
        )
        return int(cur.lastrowid)


def get_scenario(scenario_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM scenarios WHERE id = ?", (scenario_id,)).fetchone()
    return _scenario_from_row(row) if row else None


def update_scenario(scenario_id: int, name: str, nodes: list[dict], edges: list[dict]) -> bool:
    nodes_json = json.dumps(nodes)
    edges_json = json.dumps(edges)
    with _conn() as conn:
        row = conn.execute(
            "SELECT nodes, edges FROM scenarios WHERE id = ?", (scenario_id,)
        ).fetchone()
        if row is None:
            return False
        conn.execute(
            "UPDATE scenarios SET name = ?, nodes = ?, edges = ?, updated_at = ? WHERE id = ?",
            (name, nodes_json, edges_json, _now(), scenario_id),
        )
        # 管网结构发生变化时，旧方案才作废
        if row["nodes"] != nodes_json or row["edges"] != edges_json:
            conn.execute("DELETE FROM solutions WHERE scenario_id = ?", (scenario_id,))
        return True


def delete_scenario(scenario_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
        return cur.rowcount > 0


def save_solution(scenario_id: int, repair_edge_id: str, must_supply: list[str],
                  result) -> dict:
    now = _now()
    with _conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO solutions(scenario_id, repair_edge_id, must_supply, status,
                                  closed_valves, supplied, unsupplied,
                                  outage_households, valve_count, solve_time_ms,
                                  message, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                scenario_id,
                repair_edge_id,
                json.dumps(must_supply),
                result.status,
                json.dumps(result.closed_valves),
                json.dumps(result.supplied),
                json.dumps(result.unsupplied),
                result.outage_households,
                result.valve_count,
                result.solve_time_ms,
                result.message,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM solutions WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _solution_from_row(row)


def latest_solution(scenario_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM solutions WHERE scenario_id = ? ORDER BY id DESC LIMIT 1",
            (scenario_id,),
        ).fetchone()
    return _solution_from_row(row) if row else None
