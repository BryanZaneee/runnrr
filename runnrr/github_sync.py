"""Refresh website-listed portfolio projects from public sources only."""

import argparse
import json
import logging
import time
import uuid
from html.parser import HTMLParser

import httpx

from runnrr.kb_loader import _safe_resolve
from runnrr.profiles import PROFILE_ROOT, clear_manifest_cache, load_profile
from runnrr.projects import MAX_BYTES, github_snapshot, repository_name, save_project


class PortfolioParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.projects = []
        self.row = None
        self.heading = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "article" and "work-row" in attrs.get("class", "").split():
            self.row = {"slug": attrs["data-id"], "name": "", "text": [], "repository": None}
        if self.row is None:
            return
        if tag == "h4":
            self.heading = True
        href = attrs.get("href", "")
        if href.startswith("https://github.com/"):
            self.row["repository"] = repository_name(href)

    def handle_data(self, data):
        if self.row is not None and data.strip():
            self.row["text"].append(data.strip())
            if self.heading:
                self.row["name"] += data.strip()

    def handle_endtag(self, tag):
        if tag == "h4":
            self.heading = False
        if tag == "article" and self.row is not None:
            if self.row["name"]:
                self.projects.append(self.row)
            self.row = None


def website_projects(url):
    # This scheduled task reads the owner's public portfolio, never private repos.
    if url != "https://bryanzane.com/":
        raise ValueError("Portfolio source must be https://bryanzane.com/")
    with httpx.stream("GET", url, timeout=20, follow_redirects=False) as response:
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_bytes():
            body.extend(chunk)
            if len(body) > MAX_BYTES:
                raise ValueError("Portfolio page is too large")
    parser = PortfolioParser()
    parser.feed(body.decode("utf-8"))
    if not parser.projects:
        raise ValueError("No portfolio projects found; keeping previous knowledge")
    return parser.projects


def sync(profile_id: str) -> list[str]:
    profile = load_profile(profile_id)
    config = json.loads((PROFILE_ROOT / profile_id / "github.json").read_text())
    url = config["website"]
    failures = []
    for project in website_projects(url):
        slug = profile.project_aliases.get(project["slug"], project["slug"])
        repository = project["repository"]
        try:
            documents = github_snapshot(repository)[1] if repository else {}
            stamp = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
            documents["website.md"] = (
                f"# {project['name']}\n\nSource: {url}#project-{project['slug']}\nRetrieved: {stamp}\n\n"
                + "\n\n".join(project["text"])
            )
            if not repository:
                documents["website.md"] += (
                    "\n\nNo public repository is linked on the portfolio. These are public website facts, not a code review.\n"
                )
            documents = {"website.md": documents["website.md"], **documents}
            path = _safe_resolve(f"github/{slug}.md", root=profile.kb_root)
            path.parent.mkdir(parents=True, exist_ok=True)
            pending = _safe_resolve(f"github/{slug}.pending", root=profile.kb_root)
            pending.write_text(
                "\n\n".join(f"## {name}\n\n{body}" for name, body in documents.items()),
                encoding="utf-8",
            )
            pending.replace(path)
            identity = (
                f"https://github.com/{repository.lower()}"
                if repository
                else url + "#project-" + project["slug"]
            )
            save_project(
                "public",
                project["name"],
                documents,
                repository,
                str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
            )
            print(f"Updated {project['name']} ({'website + GitHub' if repository else 'website'})")
        except Exception:
            logging.exception(
                "Could not refresh %s; retaining its previous snapshot", project["name"]
            )
            failures.append(project["name"])
    clear_manifest_cache()
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", default="personal-agent")
    args = parser.parse_args()
    raise SystemExit(1 if sync(args.profile) else 0)
