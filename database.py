import sqlite3
import json
from datetime import datetime

DB_PATH = "rente.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS scenarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                params TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        conn.commit()


def list_scenarios():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, created_at, updated_at FROM scenarios ORDER BY updated_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


def load_scenario(scenario_id):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, params FROM scenarios WHERE id=?", (scenario_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["params"] = json.loads(d["params"])
    return d


def save_scenario(name, params, scenario_id=None):
    now = datetime.now().isoformat(timespec="seconds")
    params_json = json.dumps(params, ensure_ascii=False)
    with get_conn() as conn:
        if scenario_id:
            conn.execute(
                "UPDATE scenarios SET name=?, params=?, updated_at=? WHERE id=?",
                (name, params_json, now, scenario_id),
            )
            conn.commit()
            return scenario_id
        else:
            cur = conn.execute(
                "INSERT INTO scenarios (name, params, created_at, updated_at) VALUES (?,?,?,?)",
                (name, params_json, now, now),
            )
            conn.commit()
            return cur.lastrowid


def delete_scenario(scenario_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM scenarios WHERE id=?", (scenario_id,))
        conn.commit()
