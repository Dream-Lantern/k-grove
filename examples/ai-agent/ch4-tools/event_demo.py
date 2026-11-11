"""SQLite event demo: duplicate delivery and a real consumer process crash.

All effects are local database writes. No queue, remote benchmark or notification.
"""
import json
import os
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


EVENT = {
    "event_id": "evt-completed-42-g1",
    "type": "TaskCompleted",
    "task_id": "task-42",
    "target_generation": 1,
    "payload": {"outcome": "SUCCEEDED"},
}


def consume(database, *, crash=False):
    with closing(sqlite3.connect(database)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        event_id, payload = db.execute("SELECT event_id, payload FROM outbox").fetchone()
        event = json.loads(payload)
        assert event_id == event["event_id"]
        previous = db.execute(
            "SELECT payload FROM consumed WHERE event_id = ?", (event_id,)
        ).fetchone()
        if previous:
            if previous[0] != payload:
                raise ValueError("same event_id with different payload")
            return "duplicate: reused committed result"
        current = db.execute(
            "SELECT generation FROM tasks WHERE task_id = ?", (event["task_id"],)
        ).fetchone()
        if not current or current[0] != event["target_generation"]:
            raise ValueError("unknown task or stale generation")
        # The effect here is LOCAL. A remote effect cannot join this transaction.
        db.execute("INSERT INTO followups VALUES (?, ?)", (event_id, "ANALYZE_REPORT"))
        db.execute("INSERT INTO consumed VALUES (?, ?)", (event_id, payload))
        if crash:
            os._exit(23)  # Simulate death before commit, bypassing Python cleanup.
    return "consumed: one durable follow-up"


def demo():
    with tempfile.TemporaryDirectory(prefix="chapter4-events-") as folder:
        database = str(Path(folder) / "events.sqlite")
        with closing(sqlite3.connect(database)) as db, db:
            db.executescript("""
                CREATE TABLE tasks(task_id TEXT PRIMARY KEY, generation INTEGER, status TEXT);
                CREATE TABLE outbox(event_id TEXT PRIMARY KEY, payload TEXT);
                CREATE TABLE consumed(event_id TEXT PRIMARY KEY, payload TEXT);
                CREATE TABLE followups(event_id TEXT PRIMARY KEY, action TEXT);
            """)
            # The Worker persists completion and its event atomically.
            db.execute("INSERT INTO tasks VALUES ('task-42', 1, 'COMPLETED')")
            db.execute("INSERT INTO outbox VALUES (?, ?)",
                       (EVENT["event_id"], json.dumps(EVENT, sort_keys=True)))
        print("producer: task-42 COMPLETED + TaskCompleted committed")
        child = subprocess.run([sys.executable, str(Path(__file__).resolve()),
                                "--crash", database], check=False)
        assert child.returncode == 23
        with closing(sqlite3.connect(database)) as db, db:
            assert db.execute("SELECT COUNT(*) FROM consumed").fetchone()[0] == 0
            assert db.execute("SELECT COUNT(*) FROM followups").fetchone()[0] == 0
        print("crash: uncommitted consumption and local effect rolled back")
        print(consume(database))
        print(consume(database))
        with closing(sqlite3.connect(database)) as db, db:
            assert db.execute("SELECT COUNT(*) FROM followups").fetchone()[0] == 1
        print("verified: followups=1 after recovery and duplicate delivery")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--crash":
        consume(sys.argv[2], crash=True)
    else:
        demo()
