"""Command line helpers for profile-scoped RAG indexes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from runnrr.profiles import AgentProfile, load_profile
from runnrr.rag.embeddings import get_embedding_provider
from runnrr.rag.indexer import Indexer
from runnrr.rag.tools import semantic_search_kb


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    profile = _load_profile(args.profile, args.profile_root)
    embedding = get_embedding_provider(args.backend, args.model)
    index_dir = _index_dir(args, profile)

    if args.command == "build":
        report = Indexer(profile, embedding, index_dir=index_dir).build(force=args.force)
        _print_json(report.to_dict())
        return 0

    if args.command == "info":
        info = Indexer(profile, embedding, index_dir=index_dir).info()
        _print_json(info.to_dict())
        return 0

    if args.command == "query":
        results = semantic_search_kb(
            args.query,
            k=args.k,
            profile=profile,
            embedding_provider=embedding,
            index_dir=index_dir,
        )
        _print_json(results)
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m runnrr.rag.cli")
    parser.add_argument(
        "--profile-root",
        type=Path,
        default=None,
        help="Optional profile root for tests or alternate deployments.",
    )
    parser.add_argument(
        "--index-root",
        type=Path,
        default=None,
        help="Optional root directory containing one index directory per profile.",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        default=None,
        help="Optional exact index directory for this profile.",
    )
    parser.add_argument(
        "--backend",
        choices=["fake", "voyage", "local"],
        default=None,
        help="Embedding backend override. Use --backend fake for tests.",
    )
    parser.add_argument("--model", default=None, help="Embedding model override.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    build = subparsers.add_parser("build", help="Build or update a profile index.")
    build.add_argument("profile")
    build.add_argument("--force", action="store_true", help="Rebuild from scratch.")

    info = subparsers.add_parser("info", help="Inspect a profile index.")
    info.add_argument("profile")

    query = subparsers.add_parser("query", help="Query a built profile index.")
    query.add_argument("profile")
    query.add_argument("query")
    query.add_argument("--k", type=int, default=5)
    return parser


def _load_profile(profile_id: str, profile_root: Path | None) -> AgentProfile:
    return load_profile(profile_id, profile_root=profile_root)


def _index_dir(args: argparse.Namespace, profile: AgentProfile) -> Path | None:
    if args.index_dir is not None:
        return args.index_dir
    if args.index_root is not None:
        return args.index_root / profile.id
    return None


def _print_json(value) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
