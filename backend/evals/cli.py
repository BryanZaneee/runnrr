"""CLI for RAG evaluation runs, comparison, and reporting."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from backend.config import PROFILE_ROOT
from backend.evals.datasets import load_rag_dataset
from backend.evals.records import recall_metric
from backend.evals.runner import RAGEvaluator
from backend.profiles import load_profile
from backend.rag.embeddings import get_embedding_provider


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "compare":
        return _cmd_compare(args)
    if args.command == "list":
        return _cmd_list(args)
    if args.command == "report":
        return _cmd_report(args)

    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_run(args: argparse.Namespace) -> int:
    if args.dataset != "rag":
        raise SystemExit("only --dataset rag is supported")
    profile = load_profile(args.profile, profile_root=args.profile_root)
    dataset = load_rag_dataset(args.profile, profile_root=args.profile_root)
    embedding = get_embedding_provider(args.backend, args.embed_model)
    evaluator = RAGEvaluator(profile, embedding_provider=embedding)

    variants = tuple(v.strip() for v in args.variants.split(",") if v.strip())
    if args.mode == "retrieval-only":
        result = evaluator.run_retrieval_only(dataset, variants=variants, k=args.k)
    else:
        if not args.model_id:
            raise SystemExit("end-to-end mode requires --model <MODEL_REGISTRY id>")
        for variant in variants:
            result = evaluator.run_end_to_end(
                dataset, variant=variant, model_id=args.model_id
            )
    _print_json(result.summary)
    print(f"run_dir: {result.run_dir}", flush=True)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(args.profile, args.profile_root, args.run_id, args.latest)
    records = _load_records(run_dir)
    base_variant = args.baseline
    cand_variant = args.candidate

    def by_variant(variant: str) -> dict[str, dict]:
        return {
            r["case_id"]: r
            for r in records
            if r.get("variant") == variant and r.get("status") == "ok"
        }

    base = by_variant(base_variant)
    cand = by_variant(cand_variant)
    case_ids = sorted(set(base) | set(cand))

    metrics = (
        "recall_at_k",
        "context_precision",
        "reciprocal_rank",
        "faithfulness",
        "answer_relevance",
    )
    print(f"compare {args.profile} run={run_dir.name}")
    print(f"  baseline={base_variant}  candidate={cand_variant}")
    print()
    header = f"{'metric':<22} {'base':>8} {'cand':>8} {'delta':>8} {'lift':>8}"
    print(header)
    print("-" * len(header))

    for key in metrics:
        b_vals = [
            base[c]["metrics"][key]
            for c in case_ids
            if c in base and base[c]["metrics"].get(key) is not None
        ]
        c_vals = [
            cand[c]["metrics"][key]
            for c in case_ids
            if c in cand and cand[c]["metrics"].get(key) is not None
        ]
        if not b_vals or not c_vals:
            continue
        b_avg = sum(b_vals) / len(b_vals)
        c_avg = sum(c_vals) / len(c_vals)
        delta = c_avg - b_avg
        lift = (delta / b_avg) if b_avg else float("nan")
        print(
            f"{key:<22} {b_avg:8.3f} {c_avg:8.3f} {delta:+8.3f} {lift:+8.1%}"
        )

    b_lat = _avg_latency(base.values())
    c_lat = _avg_latency(cand.values())
    if b_lat is not None and c_lat is not None:
        print(f"{'latency_ms_avg':<22} {b_lat:8.1f} {c_lat:8.1f} {c_lat - b_lat:+8.1f}")

    failing = []
    for cid in case_ids:
        if cid not in base or cid not in cand:
            continue
        br = recall_metric(base[cid]["metrics"])
        cr = recall_metric(cand[cid]["metrics"])
        if br is not None and cr is not None and cr < br:
            failing.append(cid)

    if failing:
        print()
        print("cases where candidate recall < baseline:")
        for cid in failing:
            print(f"  - {cid}")
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    runs_root = _runs_root(args.profile, args.profile_root)
    if not runs_root.is_dir():
        print(f"no runs directory: {runs_root}")
        return 0

    rows: list[tuple[str, str, str]] = []
    for run_dir in sorted(runs_root.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        summary_path = run_dir / "summary.json"
        if not summary_path.is_file():
            continue
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        created = summary.get("created_at", "?")
        recalls = []
        for variant, stats in (summary.get("per_variant") or {}).items():
            r = recall_metric(stats)
            if r is not None:
                recalls.append(f"{variant}={r:.2f}")
        headline = ", ".join(recalls) if recalls else "(no recall)"
        rows.append((run_dir.name, created, headline))

    if not rows:
        print(f"no runs under {runs_root}")
        return 0

    print(f"runs for {args.profile}:")
    for run_id, created, headline in rows:
        print(f"  {run_id}  {created}  {headline}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(
        args.profile, args.profile_root, getattr(args, "run_id", None), args.latest
    )
    summary_path = run_dir / "summary.json"
    if not summary_path.is_file():
        raise SystemExit(f"summary not found: {summary_path}")
    _print_json(json.loads(summary_path.read_text(encoding="utf-8")))
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.evals.cli")
    parser.add_argument(
        "--profile-root",
        type=Path,
        default=None,
        help="Optional profile root for tests or alternate deployments.",
    )
    parser.add_argument(
        "--backend",
        choices=["fake", "voyage", "local"],
        default=None,
        help="Embedding backend override. Use --backend fake for tests.",
    )
    parser.add_argument("--model", dest="embed_model", default=None, help="Embedding model override.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run an eval dataset.")
    run.add_argument("profile")
    run.add_argument("--dataset", default="rag", choices=["rag"])
    run.add_argument(
        "--mode",
        required=True,
        choices=["retrieval-only", "end-to-end"],
    )
    run.add_argument(
        "--variants",
        default="keyword,hybrid,hybrid_rerank",
        help="Comma-separated retrieval variants.",
    )
    run.add_argument(
        "--model",
        dest="model_id",
        default=None,
        help="MODEL_REGISTRY id for end-to-end agent runs.",
    )
    run.add_argument("--k", type=int, default=5)

    compare = subparsers.add_parser("compare", help="Compare two variants in a run.")
    compare.add_argument("profile")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--run", dest="run_id", default=None)
    compare.add_argument("--latest", action="store_true")

    list_cmd = subparsers.add_parser("list", help="List eval runs for a profile.")
    list_cmd.add_argument("profile")

    report = subparsers.add_parser("report", help="Print a run summary.")
    report.add_argument("profile")
    report.add_argument("--latest", action="store_true")
    report.add_argument("--run", dest="run_id", default=None)

    return parser


def _runs_root(profile_id: str, profile_root: Path | None) -> Path:
    root = (profile_root or PROFILE_ROOT).resolve()
    return root / profile_id / "evals" / "runs"


def _resolve_run_dir(
    profile_id: str,
    profile_root: Path | None,
    run_id: str | None,
    use_latest: bool,
) -> Path:
    runs_root = _runs_root(profile_id, profile_root)
    if run_id:
        run_dir = runs_root / run_id
        if not run_dir.is_dir():
            raise SystemExit(f"run not found: {run_dir}")
        return run_dir
    if use_latest or not run_id:
        if not runs_root.is_dir():
            raise SystemExit(f"no runs directory: {runs_root}")
        dirs = sorted(
            (d for d in runs_root.iterdir() if d.is_dir()),
            key=lambda p: p.name,
            reverse=True,
        )
        if not dirs:
            raise SystemExit(f"no runs under {runs_root}")
        return dirs[0]
    raise SystemExit("specify --run <id> or --latest")


def _load_records(run_dir: Path) -> list[dict]:
    path = run_dir / "records.jsonl"
    if not path.is_file():
        raise SystemExit(f"records not found: {path}")
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rec = json.loads(line)
            metrics = rec.get("metrics")
            if isinstance(metrics, dict) and "recall_at_k" not in metrics:
                metrics["recall_at_k"] = recall_metric(metrics)
            records.append(rec)
    return records


def _avg_latency(records: list[dict]) -> float | None:
    vals = [float(r["latency_ms"]) for r in records if r.get("latency_ms") is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    raise SystemExit(main())
