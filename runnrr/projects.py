"""Small, owner-scoped project knowledge collections stored in SQLite."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from runnrr.ratelimit import limiter

router = APIRouter(prefix="/api/projects", tags=["projects"])
DB_PATH = Path(os.environ.get("RUNNRR_PROJECT_DB", "data/projects.sqlite3"))
PUBLIC_DEMO = os.environ.get("RUNNRR_PUBLIC_DEMO", "0") == "1"
MAX_BYTES = 1_000_000
TEXT_EXTENSIONS = {
    ".md",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".mjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".csv",
}


class ProjectBodyLimit:
    """Bound public uploads before JSON parsing, including chunked requests."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope.get("method") != "POST"
            or not scope["path"].startswith("/api/projects")
        ):
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            size += len(chunk)
            if size > 2_000_000:
                return await JSONResponse(
                    {"detail": "Upload is too large. Choose fewer text files."}, status_code=413
                )(scope, receive, send)
            chunks.append(chunk)
            if not message.get("more_body"):
                break
        pending = True

        async def replay():
            nonlocal pending
            if pending:
                pending = False
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


@contextmanager
def database():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, name TEXT NOT NULL,
        repository TEXT, documents TEXT NOT NULL, updated REAL NOT NULL)""")
    try:
        with db:
            yield db
    finally:
        db.close()


def owner_key(request: Request) -> str:
    token = request.headers.get("X-Workspace-Owner", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", token):
        raise HTTPException(401, "This workspace needs its browser key. Reload and try again.")
    return hashlib.sha256(token.encode()).hexdigest()


def summary(row, owner: str) -> dict:
    return {
        "id": row["id"],
        "name": row["name"],
        "repository": row["repository"],
        "updated": row["updated"],
        "file_count": row["file_count"] if "file_count" in row.keys() else len(row["documents"]),
        "shared": row["owner"] == "public",
        "editable": row["owner"] == owner,
    }


KNOWLEDGE_PROJECT_ID = "knowledge-frampton"


def knowledge_project():
    from runnrr.kb_loader import iter_markdown_files
    from runnrr.profiles import load_profile

    profile = load_profile("frampton")
    return {
        "id": KNOWLEDGE_PROJECT_ID,
        "name": "Dark Souls knowledge",
        "repository": None,
        "updated": 0,
        "file_count": sum(1 for _ in iter_markdown_files(root=profile.kb_root)),
        "shared": True,
        "editable": False,
        "knowledge_profile": "frampton",
    }


def get_project(project_id: str, owner: str) -> dict:
    if project_id == KNOWLEDGE_PROJECT_ID:
        return knowledge_project() | {"owner": "public", "documents": {}}
    with database() as db:
        row = db.execute(
            "SELECT * FROM projects WHERE id=? AND owner IN (?, 'public')", (project_id, owner)
        ).fetchone()
    if (
        row is None
        or (row["owner"] == "public" and owner != "public" and not PUBLIC_DEMO)
        or (PUBLIC_DEMO and row["owner"] != "public")
    ):
        raise HTTPException(404, "Project not found in this workspace.")
    return dict(row) | {"documents": json.loads(row["documents"])}


def validate_documents(documents: dict[str, str]) -> dict[str, str]:
    if not 1 <= len(documents) <= 80:
        raise HTTPException(400, "Choose between 1 and 80 text files.")
    if sum(len(v.encode()) for v in documents.values()) > MAX_BYTES:
        raise HTTPException(400, "Project files must total less than 1 MB.")
    for name, content in documents.items():
        path = PurePosixPath(name)
        if (
            len(name) > 240
            or path.is_absolute()
            or "\\" in name
            or any(p.startswith(".") or p in {"node_modules", "vendor"} for p in path.parts)
            or path.suffix.lower() not in TEXT_EXTENSIONS
            or "\x00" in content
            or any(ord(c) < 32 for c in name)
            or len(content.encode()) > 200_000
        ):
            raise HTTPException(400, f"Unsupported file: {name[:80]}")
    return documents


def save_project(owner: str, name: str, documents: dict, repository=None, project_id=None):
    validate_documents(documents)
    project_id = project_id or str(uuid.uuid4())
    with database() as db:
        db.execute("BEGIN IMMEDIATE")
        exists = db.execute("SELECT owner FROM projects WHERE id=?", (project_id,)).fetchone()
        if exists and exists["owner"] != owner:
            raise HTTPException(403, "This project is read-only.")
        if not exists and owner != "public":
            count = db.execute("SELECT count(*) FROM projects WHERE owner=?", (owner,)).fetchone()[
                0
            ]
            total = db.execute("SELECT count(*) FROM projects").fetchone()[0]
            if count >= 20 or total >= 500:
                raise HTTPException(
                    409, "Project storage is full. Remove a project before adding another."
                )
        db.execute(
            "INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?,?)",
            (project_id, owner, name.strip(), repository, json.dumps(documents), time.time()),
        )
    return get_project(project_id, owner)


def repository_name(value: str) -> str:
    value = value.strip().removeprefix("https://github.com/").removesuffix("/").removesuffix(".git")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value):
        raise HTTPException(400, "Use a public GitHub URL or owner/repository.")
    return value


def github_snapshot(repository: str) -> tuple[str, dict[str, str]]:
    repository = repository_name(repository)
    # Fixed host, no credentials or redirects: public read-only GitHub content only.
    with httpx.Client(
        timeout=15,
        follow_redirects=False,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Runnrr"},
    ) as client:

        def get(suffix, optional=False):
            with client.stream("GET", f"https://api.github.com/repos/{repository}{suffix}") as r:
                if optional and r.status_code == 404:
                    return None
                if r.status_code != 200:
                    raise HTTPException(
                        502,
                        "GitHub could not refresh this public repository. Check its name or try again later.",
                    )
                body = bytearray()
                for chunk in r.iter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_BYTES:
                        raise HTTPException(400, "GitHub document is too large.")
                return json.loads(body)

        try:
            meta = get("")
            if meta.get("private"):
                raise HTTPException(400, "Only public repositories are supported.")
            readme = get("/readme", optional=True)
            release = get("/releases/latest", optional=True)
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(
                502, "GitHub is unavailable. Your previous project copy is unchanged."
            ) from exc
    stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    docs = {
        "repository.md": f"# {meta['name']}\n\nSource: https://github.com/{repository}\nRetrieved: {stamp}\n\n{meta.get('description') or ''}\n\nPrimary language: {meta.get('language')}\nLast push: {meta.get('pushed_at')}\nArchived: {meta.get('archived')}\nHomepage: {meta.get('homepage') or 'Not listed'}\n"
    }
    if readme:
        docs["README.md"] = base64.b64decode(readme["content"]).decode("utf-8", errors="replace")[
            :180_000
        ]
    if release:
        docs["release.md"] = (
            f"# Latest release: {release['tag_name']}\n\n{release.get('html_url')}\n{release.get('published_at')}\n\n{release.get('body') or ''}"[
                :180_000
            ]
        )
    validate_documents(docs)
    return meta["name"], docs


class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    repository: str | None = Field(default=None, max_length=200)
    documents: dict[str, str] = Field(default_factory=dict, max_length=80)


@router.get("")
def list_projects(request: Request):
    owner = owner_key(request)
    with database() as db:
        rows = db.execute(
            "SELECT id, owner, name, repository, updated, (SELECT count(*) FROM json_each(documents)) AS file_count FROM projects WHERE owner=? ORDER BY name COLLATE NOCASE",
            ("public" if PUBLIC_DEMO else owner,),
        ).fetchall()
    return {
        "projects": [knowledge_project(), *[summary(row, owner) for row in rows]],
        "mode": "portfolio" if PUBLIC_DEMO else "local",
    }


@router.post("")
@limiter.limit("6/minute;30/hour")
def create_project(request: Request, req: ProjectInput):
    if PUBLIC_DEMO:
        raise HTTPException(
            403,
            "The online demo uses read-only portfolio projects. Add your own folders in the local app.",
        )
    owner = owner_key(request)
    if not req.name.strip():
        raise HTTPException(400, "Give the project a name.")
    repository = repository_name(req.repository) if req.repository else None
    documents = github_snapshot(repository)[1] if repository else req.documents
    row = save_project(owner, req.name, documents, repository)
    return summary(row, owner)


@router.post("/{project_id}/refresh")
@limiter.limit("3/minute;15/hour")
def refresh_project(request: Request, project_id: str):
    if PUBLIC_DEMO:
        raise HTTPException(
            403,
            "The online demo uses read-only portfolio projects. Add your own folders in the local app.",
        )
    owner = owner_key(request)
    row = get_project(project_id, owner)
    if row["owner"] != owner or not row["repository"]:
        raise HTTPException(403, "Only your GitHub projects can be refreshed here.")
    _, documents = github_snapshot(row["repository"])
    saved = save_project(owner, row["name"], documents, row["repository"], project_id)
    return summary(saved, owner)


@router.post("/{project_id}/delete")
@limiter.limit("10/minute")
def delete_project(request: Request, project_id: str):
    if PUBLIC_DEMO:
        raise HTTPException(
            403,
            "The online demo uses read-only portfolio projects. Add your own folders in the local app.",
        )
    owner = owner_key(request)
    row = get_project(project_id, owner)
    if row["owner"] != owner:
        raise HTTPException(403, "Shared projects are read-only.")
    with database() as db:
        db.execute("DELETE FROM projects WHERE id=? AND owner=?", (project_id, owner))
    return {"deleted": True}
