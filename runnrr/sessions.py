"""Small SQLite store for owner-scoped threads and provider conversation state."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from runnrr.projects import owner_key

DB_PATH = Path(os.environ.get("RUNNRR_SESSION_DB", "data/sessions.sqlite3"))
router = APIRouter(prefix="/api/threads", tags=["threads"])
MAX_STATE_BYTES = 2_000_000


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS threads (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, ui TEXT NOT NULL,
            session TEXT, updated REAL NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)""")
        db.execute("""CREATE TABLE IF NOT EXISTS thread_turns (
            id TEXT PRIMARY KEY, thread_id TEXT NOT NULL, prompt TEXT NOT NULL,
            events TEXT NOT NULL DEFAULT '[]', finished INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL)""")
        db.execute("CREATE INDEX IF NOT EXISTS turns_thread ON thread_turns(thread_id, created)")
        with db:
            expired = time.time() - 86400
            db.execute(
                "DELETE FROM thread_turns WHERE thread_id IN (SELECT id FROM threads WHERE deleted=1 AND updated<?)",
                (expired,),
            )
            db.execute("DELETE FROM threads WHERE deleted=1 AND updated<?", (expired,))
            db.commit()
            yield db
    finally:
        db.close()


def encode(value):
    return json.dumps(value, ensure_ascii=False, default=lambda v: v.model_dump(mode="json"))


class ThreadInput(BaseModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    profileId: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    projectId: str | None = Field(default=None, max_length=64)
    title: str = Field(default="New thread", max_length=200)
    draft: str = Field(default="", max_length=4000)
    pinned: bool = False
    settled: bool = False
    snoozedUntil: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    created: float = Field(ge=0, allow_inf_nan=False)
    updated: float = Field(ge=0, allow_inf_nan=False)


def owned(db, thread_id, owner):
    row = db.execute(
        "SELECT * FROM threads WHERE id=? AND owner=? AND deleted=0", (thread_id, owner)
    ).fetchone()
    if row is None:
        raise HTTPException(404, "Thread not found in this workspace.")
    return row


def save_ui(owner: str, state: ThreadInput):
    ui = state.model_dump()
    if ui["snoozedUntil"]:
        ui["pinned"] = False
    if ui["settled"]:
        ui["snoozedUntil"] = None
    if ui["snoozedUntil"] and ui["snoozedUntil"] <= time.time() * 1000:
        ui["snoozedUntil"] = None
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT * FROM threads WHERE id=?", (state.id,)).fetchone()
        if row and row["owner"] != owner:
            raise HTTPException(404, "Thread not found in this workspace.")
        if (
            row
            and db.execute(
                "SELECT 1 FROM thread_turns WHERE thread_id=? LIMIT 1", (state.id,)
            ).fetchone()
        ):
            previous = json.loads(row["ui"])
            if any(previous.get(k) != ui.get(k) for k in ("profileId", "model", "projectId")):
                raise HTTPException(
                    409, "Start a new thread to change its assistant, model, or project."
                )
        if not row:
            count = db.execute(
                "SELECT count(*) FROM threads WHERE owner=? AND deleted=0", (owner,)
            ).fetchone()[0]
            total = db.execute("SELECT count(*) FROM threads WHERE deleted=0").fetchone()[0]
            if count >= 100 or total >= 1000:
                raise HTTPException(
                    409, "Saved thread storage is full. Delete an old thread first."
                )
        db.execute(
            """INSERT INTO threads(id,owner,ui,updated) VALUES (?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET ui=excluded.ui, updated=excluded.updated, deleted=0""",
            (state.id, owner, encode(ui), time.time()),
        )
    return ui


def ensure_thread(thread_id, owner, profile, model, project_id):
    with database() as db:
        row = db.execute("SELECT owner,deleted FROM threads WHERE id=?", (thread_id,)).fetchone()
    if row:
        if row["owner"] != owner or row["deleted"]:
            raise HTTPException(404, "Thread not found in this workspace.")
        return
    now = time.time() * 1000
    save_ui(
        owner,
        ThreadInput(
            id=thread_id,
            profileId=profile,
            model=model,
            projectId=project_id,
            created=now,
            updated=now,
        ),
    )


def load_session(thread_id: str, owner: str):
    with database() as db:
        row = owned(db, thread_id, owner)
    return json.loads(row["session"]) if row["session"] else None


def begin_turn(thread_id, owner, turn_id, prompt, profile, model, project_id):
    with database() as db:
        ui = json.loads(owned(db, thread_id, owner)["ui"])
        if (ui["profileId"], ui["model"], ui["projectId"]) != (profile, model, project_id):
            raise HTTPException(
                409, "The saved thread has a different assistant, model, or project."
            )
        if ui["settled"] or (ui["snoozedUntil"] and ui["snoozedUntil"] > time.time() * 1000):
            raise HTTPException(409, "Restore this thread before sending a message.")
        db.execute(
            "INSERT INTO thread_turns(id,thread_id,prompt,created) VALUES (?,?,?,?)",
            (turn_id, thread_id, prompt, time.time()),
        )


def finish_turn(thread_id, owner, turn_id, events, session):
    payload = encode({k: v for k, v in session.items() if k not in {"busy", "workspace_owner"}})
    event_json = encode(events)
    if len(payload.encode()) + len(event_json.encode()) > MAX_STATE_BYTES:
        raise ValueError("Thread is too large to save. Start a new thread.")
    with database() as db:
        owned(db, thread_id, owner)
        db.execute(
            "UPDATE threads SET session=?, updated=? WHERE id=?", (payload, time.time(), thread_id)
        )
        db.execute(
            "UPDATE thread_turns SET events=?, finished=1 WHERE id=? AND thread_id=?",
            (event_json, turn_id, thread_id),
        )


@router.get("")
def list_threads(request: Request):
    owner = owner_key(request)
    with database() as db:
        rows = db.execute(
            "SELECT id,ui FROM threads WHERE owner=? AND deleted=0 ORDER BY updated DESC", (owner,)
        ).fetchall()
        result = []
        for row in rows:
            ui = json.loads(row["ui"])
            if ui["snoozedUntil"] and ui["snoozedUntil"] <= time.time() * 1000:
                ui["snoozedUntil"] = None
            turns = db.execute(
                "SELECT prompt,events,finished FROM thread_turns WHERE thread_id=? ORDER BY created",
                (row["id"],),
            ).fetchall()
            ui["history"] = [dict(t) | {"events": json.loads(t["events"])} for t in turns]
            result.append(ui)
    return {"threads": result}


@router.post("")
def update_thread(request: Request, state: ThreadInput):
    return save_ui(owner_key(request), state)


@router.post("/{thread_id}/delete")
def delete_thread(request: Request, thread_id: str):
    from runnrr.app import SESSIONS

    owner = owner_key(request)
    with database() as db:
        owned(db, thread_id, owner)
        if SESSIONS.get(thread_id, {}).get("busy"):
            raise HTTPException(409, "Wait for the response before deleting this thread.")
        db.execute("UPDATE threads SET deleted=1,updated=? WHERE id=?", (time.time(), thread_id))
    SESSIONS.pop(thread_id, None)
    return {"deleted": True}
