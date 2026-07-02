"""Sales profile catalog, lead, and checkout preview tools."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from backend.tool_errors import ToolExecutionError
from backend.tools.definitions import ToolDef
from backend.tools.source_metadata import catalog_lookup_metadata, static_source_metadata


def _require_data_root(data_root: Path | None) -> Path:
    if data_root is None:
        raise ToolExecutionError("active profile does not define data_root")
    return data_root.resolve()


def _load_catalog(data_root: Path | None) -> dict[str, Any]:
    root = _require_data_root(data_root)
    # .resolve() follows symlinks, so a catalog.json symlinked outside the data
    # root fails the relative_to check below.
    path = (root / "catalog.json").resolve()
    try:
        path.relative_to(root)
    except ValueError as e:
        raise ToolExecutionError("catalog path escapes data root") from e
    if not path.exists() or not path.is_file():
        raise ToolExecutionError("catalog.json not found for active profile")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ToolExecutionError(f"catalog.json is invalid JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("packages"), list):
        raise ToolExecutionError("catalog.json must contain a packages array")
    return data


def _package_text(package: dict[str, Any]) -> str:
    fields = [
        package.get("id", ""),
        package.get("name", ""),
        package.get("category", ""),
        package.get("description", ""),
        package.get("best_for", ""),
        " ".join(str(v) for v in package.get("keywords", [])),
        " ".join(str(v) for v in package.get("features", [])),
    ]
    return " ".join(str(v).lower() for v in fields)


def catalog_lookup(
    query: str,
    *,
    category: str = "",
    max_results: int = 5,
    data_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip():
        raise ToolExecutionError("query must be a non-empty string")
    try:
        max_results = max(1, min(int(max_results), 10))
    except (TypeError, ValueError) as e:
        raise ToolExecutionError("max_results must be an integer") from e

    catalog = _load_catalog(data_root)
    q_terms = [term for term in re.split(r"\W+", query.lower()) if term]
    category_norm = str(category or "").strip().lower()
    matches: list[tuple[int, dict[str, Any]]] = []
    for package in catalog["packages"]:
        if not isinstance(package, dict):
            continue
        if category_norm and str(package.get("category", "")).lower() != category_norm:
            continue
        text = _package_text(package)
        score = sum(1 for term in q_terms if term in text)
        if score or not q_terms:
            matches.append((score, package))

    matches.sort(key=lambda item: (-item[0], str(item[1].get("id", ""))))
    packages = [
        {
            "id": pkg.get("id", ""),
            "name": pkg.get("name", ""),
            "category": pkg.get("category", ""),
            "description": pkg.get("description", ""),
            "best_for": pkg.get("best_for", ""),
            "price_display": pkg.get("price_display", ""),
            "timeline": pkg.get("timeline", ""),
            "features": pkg.get("features", []),
            "next_step": pkg.get("next_step", ""),
        }
        for _, pkg in matches[:max_results]
    ]
    return {
        "query": query.strip(),
        "category": category_norm,
        "matches": packages,
        "catalog": catalog.get("name", "Product catalog"),
    }


def _catalog_package_by_id(data_root: Path | None, package_id: str) -> dict[str, Any]:
    catalog = _load_catalog(data_root)
    wanted = str(package_id or "").strip()
    for package in catalog["packages"]:
        if isinstance(package, dict) and package.get("id") == wanted:
            return package
    raise ToolExecutionError(f"unknown package_id: {package_id}")


def _recommend_package_id(use_case: str, integrations: list[str]) -> tuple[str, list[str]]:
    text = f"{use_case} {' '.join(integrations)}".lower()
    reasons: list[str] = []
    if any(term in text for term in ("research", "analyst", "market", "competitor", "brief")):
        reasons.append("research-oriented use case")
        return "research-profile", reasons
    if any(term in text for term in ("sales", "lead", "revenue", "pricing", "checkout")):
        reasons.append("sales or qualification workflow")
        return "sales-profile", reasons
    if any(term in text for term in ("tool", "api", "integration", "stripe", "calendar", "crm")):
        reasons.append("custom tool or integration need")
        return "custom-tools", reasons
    if any(term in text for term in ("production", "deploy", "security", "rate", "budget", "logging")):
        reasons.append("production readiness concern")
        return "production-hardening", reasons
    reasons.append("starter website widget fit")
    return "starter-widget", reasons


def qualify_lead(
    use_case: str,
    *,
    urgency: str = "",
    team_size: str = "",
    budget_range: str = "",
    integrations: list[str] | None = None,
    data_root: Path | None = None,
) -> dict[str, Any]:
    if not isinstance(use_case, str) or not use_case.strip():
        raise ToolExecutionError("use_case must be a non-empty string")
    integrations = integrations or []
    if not isinstance(integrations, list) or any(not isinstance(v, str) for v in integrations):
        raise ToolExecutionError("integrations must be a list of strings")

    missing: list[str] = []
    if not str(urgency or "").strip():
        missing.append("urgency")
    if not str(team_size or "").strip():
        missing.append("team_size")
    if not str(budget_range or "").strip():
        missing.append("budget_range")

    package_id, reasons = _recommend_package_id(use_case, integrations)
    package = _catalog_package_by_id(data_root, package_id)

    urgency_text = str(urgency or "").lower()
    budget_text = str(budget_range or "").lower()
    high_urgency = any(term in urgency_text for term in ("urgent", "now", "this week", "asap"))
    meaningful_budget = any(term in budget_text for term in ("5k", "10k", "5000", "10000", "approved"))
    has_integrations = bool(integrations)
    if high_urgency and (meaningful_budget or has_integrations):
        tier = "high"
    elif missing:
        tier = "needs_info"
    else:
        tier = "medium"

    return {
        "tier": tier,
        "recommended_package_id": package_id,
        "recommended_package_name": package.get("name", ""),
        "missing_questions": missing,
        "reasoning_labels": reasons
        + (["urgent timeline"] if high_urgency else [])
        + (["integration surface present"] if has_integrations else []),
        "preview_only": True,
    }


def lead_capture_preview(
    *,
    name: str,
    email: str,
    company: str = "",
    use_case: str,
    notes: str = "",
) -> dict[str, Any]:
    clean = {
        "name": str(name or "").strip(),
        "email": str(email or "").strip().lower(),
        "company": str(company or "").strip(),
        "use_case": str(use_case or "").strip(),
        "notes": str(notes or "").strip(),
    }
    if not clean["name"]:
        raise ToolExecutionError("name must be provided")
    if "@" not in clean["email"] or clean["email"].startswith("@") or clean["email"].endswith("@"):
        raise ToolExecutionError("email must look like an email address")
    if not clean["use_case"]:
        raise ToolExecutionError("use_case must be provided")

    digest = hashlib.sha256(json.dumps(clean, sort_keys=True).encode("utf-8")).hexdigest()
    return {
        "mock_lead_id": f"lead_preview_{digest[:10]}",
        "payload": clean,
        "persisted": False,
        "preview_only": True,
    }


def checkout_link_preview(
    package_id: str,
    *,
    billing_cadence: str = "one_time",
    quantity: int = 1,
    data_root: Path | None = None,
) -> dict[str, Any]:
    package = _catalog_package_by_id(data_root, package_id)
    cadence = str(billing_cadence or "one_time").strip().lower()
    if cadence not in {"one_time", "monthly", "annual"}:
        raise ToolExecutionError("billing_cadence must be one_time, monthly, or annual")
    try:
        quantity = max(1, min(int(quantity), 99))
    except (TypeError, ValueError) as e:
        raise ToolExecutionError("quantity must be an integer") from e

    line_item = {
        "package_id": package.get("id", ""),
        "name": package.get("name", ""),
        "price_display": package.get("price_display", ""),
        "billing_cadence": cadence,
        "quantity": quantity,
    }
    return {
        "checkout_url": (
            "https://checkout.example/preview/"
            f"{package.get('id', '')}?cadence={cadence}&quantity={quantity}"
        ),
        "line_items": [line_item],
        "stripe_session_created": False,
        "preview_only": True,
    }


SALES_TOOL_DEFS: tuple[ToolDef, ...] = (
    ToolDef(
        name="catalog_lookup",
        description=(
            "Search the active profile's structured product or service catalog, read "
            "from catalog.json under the profile data root."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What the visitor is looking for."},
                "category": {"type": "string", "description": "Optional catalog category filter."},
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matches to return. Default 5.",
                },
            },
            "required": ["query"],
        },
        handler=lambda args, ctx: catalog_lookup(
            args["query"],
            category=args.get("category", ""),
            max_results=args.get("max_results", 5),
            data_root=ctx.data_root,
        ),
        source_metadata=catalog_lookup_metadata,
    ),
    ToolDef(
        name="qualify_lead",
        description=(
            "Classify a prospective lead using demo qualification rules. "
            "Returns a lead tier, recommended catalog package id, missing questions, "
            "and reasoning labels. Preview-only; does not write to a CRM."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "use_case": {"type": "string"},
                "urgency": {"type": "string"},
                "team_size": {"type": "string"},
                "budget_range": {"type": "string"},
                "integrations": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["use_case"],
        },
        handler=lambda args, ctx: qualify_lead(
            args["use_case"],
            urgency=args.get("urgency", ""),
            team_size=args.get("team_size", ""),
            budget_range=args.get("budget_range", ""),
            integrations=args.get("integrations", []),
            data_root=ctx.data_root,
        ),
        source_metadata=lambda args, out, ctx: static_source_metadata(
            "qualified lead", label="Lead qualification rules", kind="lead_qualification"
        ),
    ),
    ToolDef(
        name="lead_capture_preview",
        description=(
            "Normalize lead contact details and return a mock lead id. Preview-only; "
            "does not persist data, send email, or call a CRM."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "company": {"type": "string"},
                "use_case": {"type": "string"},
                "notes": {"type": "string"},
            },
            "required": ["name", "email", "use_case"],
        },
        handler=lambda args, ctx: lead_capture_preview(
            name=args["name"],
            email=args["email"],
            company=args.get("company", ""),
            use_case=args["use_case"],
            notes=args.get("notes", ""),
        ),
        source_metadata=lambda args, out, ctx: static_source_metadata(
            "prepared lead capture preview", label="Lead capture preview", kind="lead_preview"
        ),
    ),
    ToolDef(
        name="checkout_link_preview",
        description=(
            "Return a fake checkout link and line-item summary for a Sales Concierge "
            "package. Preview-only; does not import Stripe or create a live Checkout Session."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "package_id": {"type": "string"},
                "billing_cadence": {
                    "type": "string",
                    "enum": ["one_time", "monthly", "annual"],
                    "description": "Default one_time.",
                },
                "quantity": {"type": "integer", "description": "Default 1, clamped to 1-99."},
            },
            "required": ["package_id"],
        },
        handler=lambda args, ctx: checkout_link_preview(
            args["package_id"],
            billing_cadence=args.get("billing_cadence", "one_time"),
            quantity=args.get("quantity", 1),
            data_root=ctx.data_root,
        ),
        source_metadata=lambda args, out, ctx: static_source_metadata(
            "prepared checkout preview", label="Checkout preview", kind="checkout_preview"
        ),
    ),
)
