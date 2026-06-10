"""Phase A tests: KB primitives + tool dispatcher.

Covers path safety, line-cap behavior, search semantics, and the run_tool error envelope.
"""
from __future__ import annotations

import json

import pytest

from backend.kb_loader import (
    KBError,
    list_kb,
    read_file,
    search_kb,
)
from backend.profiles import DEFAULT_PROFILE_TOOLS, AgentProfile, load_profile
from backend.tools import SCHEMAS, run_tool
from backend.tools.definitions import ToolContext
from backend.tools.personal_kb import get_project_context, get_resume_summary
from backend.tools.registry import TOOL_DEFS, TOOL_DEFS_BY_NAME, TOOL_HANDLERS


# --------------------------------------------------------------------------- #
# _safe_resolve / path safety
# --------------------------------------------------------------------------- #

class TestPathSafety:
    def test_rejects_traversal(self):
        with pytest.raises(KBError, match="escapes kb root"):
            read_file("../../../etc/passwd")

    def test_rejects_absolute_path(self):
        with pytest.raises(KBError, match="absolute paths not allowed"):
            read_file("/etc/passwd")

    def test_rejects_empty_path(self):
        with pytest.raises(KBError):
            read_file("")

    def test_rejects_non_string(self):
        with pytest.raises(KBError):
            read_file(None)  # type: ignore[arg-type]

    def test_traversal_via_subdir_in_search_blocked(self):
        with pytest.raises(KBError):
            search_kb("anything", subdir="..")

    def test_search_skips_symlink_escape(self, tmp_path):
        kb = tmp_path / "kb"
        kb.mkdir()
        outside = tmp_path / "outside.md"
        outside.write_text("outside-secret", encoding="utf-8")
        link = kb / "leak.md"
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"symlinks unavailable: {exc}")

        assert search_kb("outside-secret", root=kb) == []


# --------------------------------------------------------------------------- #
# list_kb
# --------------------------------------------------------------------------- #

class TestListKB:
    def test_root_listing_includes_subdirs(self):
        entries = list_kb("")
        kinds = {e["path"]: e["kind"] for e in entries}
        # Subdirs are present at depth 1.
        assert "resume" in kinds
        assert kinds["resume"] == "dir"
        assert "projects" in kinds
        # Files are reported with size.
        sizes = {e["path"]: e["size_bytes"] for e in entries}
        assert "INDEX.md" in sizes
        assert sizes["INDEX.md"] > 0

    def test_root_listing_does_not_recurse(self):
        # Root listing is depth-1 only so a large KB does not blow up the model's context.
        entries = list_kb("")
        paths = {e["path"] for e in entries}
        assert "projects/widget.md" not in paths
        assert "resume/resume.md" not in paths

    def test_subdir_listing(self):
        entries = list_kb("projects")
        assert any(e["path"] == "projects/widget.md" and e["kind"] == "file" for e in entries)

    def test_missing_subdir_returns_empty(self):
        assert list_kb("nonexistent-subdir") == []


# --------------------------------------------------------------------------- #
# read_file
# --------------------------------------------------------------------------- #

class TestReadFile:
    def test_basic_read(self):
        result = read_file("resume/resume.md")
        assert "Test User Resume" in result["content"]
        assert "of " in result["lines"]
        assert result["path"] == "resume/resume.md"

    def test_reports_total_lines(self, tmp_path, monkeypatch, kb_root):
        # Construct a file with known line count under the existing fixture KB.
        big = kb_root / "projects" / "big.md"
        big.write_text("\n".join(str(i) for i in range(1, 51)))  # 50 lines
        try:
            result = read_file("projects/big.md")
            assert result["lines"].endswith("of 50")
        finally:
            big.unlink()

    def test_line_slice(self):
        result = read_file("resume/resume.md", start_line=1, end_line=2)
        assert result["lines"].startswith("1-2")
        assert result["content"].count("\n") <= 1

    def test_caps_end_line_at_max(self, tmp_path, kb_root):
        # Write a 5000-line file and confirm end_line clamps to start + 2999.
        big = kb_root / "projects" / "huge.md"
        big.write_text("\n".join("line" for _ in range(5000)))
        try:
            result = read_file("projects/huge.md", start_line=1, end_line=4999)
            # MAX_LINES_PER_READ = 3000 → end clamps to start+2999 = 3000.
            assert result["lines"] == "1-3000 of 5000"
        finally:
            big.unlink()

    def test_missing_file_raises(self):
        with pytest.raises(KBError, match="not a file"):
            read_file("does/not/exist.md")


# --------------------------------------------------------------------------- #
# search_kb
# --------------------------------------------------------------------------- #

class TestSearchKB:
    def test_finds_substring(self):
        results = search_kb("zonkletcheese-42")
        assert any(r["path"] == "meta/faq.md" for r in results)
        # Each result includes context and size.
        first = results[0]
        assert "context" in first and "size_bytes" in first and "line" in first

    def test_case_insensitive(self):
        results = search_kb("CONVEX")
        assert any("convex" in r["context"].lower() or "Convex" in r["context"] for r in results)

    def test_regex_mode(self):
        results = search_kb(r"zonklet\w+", regex=True)
        assert any(r["path"] == "meta/faq.md" for r in results)

    def test_invalid_regex_raises(self):
        with pytest.raises(KBError, match="invalid regex"):
            search_kb("[unclosed", regex=True)

    def test_max_results(self):
        results = search_kb("e", max_results=3)
        assert len(results) <= 3


# --------------------------------------------------------------------------- #
# Specialized helpers
# --------------------------------------------------------------------------- #

class TestSpecialized:
    def test_get_resume_summary_matches_read_file(self):
        a = get_resume_summary()
        b = read_file("resume/resume.md")
        assert a["content"] == b["content"]

    def test_get_project_context_basic(self):
        result = get_project_context("widget")
        assert result["project"] == "widget"
        assert "test widget" in result["summary"].lower()

    def test_get_project_context_resolves_aliases(self):
        result = get_project_context(
            "bryanzane.com",
            aliases={"bryanzane.com": "widget"},
        )
        assert result["project"] == "widget"

    def test_get_project_context_unknown_raises(self):
        with pytest.raises(KBError, match="no project file"):
            get_project_context("nonexistent")

    def test_get_project_context_empty_raises(self):
        with pytest.raises(KBError):
            get_project_context("")


# --------------------------------------------------------------------------- #
# run_tool — the dispatcher and error envelope
# --------------------------------------------------------------------------- #

class TestRunTool:
    def test_dispatch_list_kb(self):
        result = run_tool("list_kb", {"subdir": ""}, tool_use_id="t1")
        assert result.is_error is False
        payload = json.loads(result.content)
        assert isinstance(payload, list) and len(payload) > 0

    def test_dispatch_read_file(self):
        result = run_tool("read_file", {"path": "resume/resume.md"}, tool_use_id="t2")
        assert result.is_error is False
        assert "Test User Resume" in json.loads(result.content)["content"]

    def test_dispatch_get_resume_summary_no_args(self):
        result = run_tool("get_resume_summary", {}, tool_use_id="t3")
        assert result.is_error is False

    def test_path_traversal_returns_is_error(self):
        result = run_tool("read_file", {"path": "../../../etc/passwd"}, tool_use_id="t4")
        assert result.is_error is True
        payload = json.loads(result.content)
        assert "error" in payload

    def test_unknown_tool_returns_is_error(self):
        result = run_tool("hack_the_planet", {}, tool_use_id="t5")
        assert result.is_error is True

    def test_missing_required_arg_returns_is_error(self):
        result = run_tool("read_file", {}, tool_use_id="t6")
        assert result.is_error is True
        assert "path" in json.loads(result.content)["error"]

    def test_unknown_project_returns_is_error(self):
        result = run_tool(
            "get_project_context", {"project_name": "nope"}, tool_use_id="t7"
        )
        assert result.is_error is True

    def test_unexpected_tool_error_is_masked_by_default(self, monkeypatch):
        from backend import config

        def explode(arguments, context):
            raise RuntimeError("secret internal failure")

        monkeypatch.setattr(config, "TOOL_DEBUG_ERRORS", False)
        monkeypatch.setitem(TOOL_HANDLERS, "explode", explode)

        result = run_tool("explode", {}, tool_use_id="t8")

        assert result.is_error is True
        payload = json.loads(result.content)
        assert payload == {"error": "tool failed unexpectedly"}
        assert "secret internal failure" not in result.content

    def test_unexpected_tool_error_reraises_in_debug_mode(self, monkeypatch):
        from backend import config

        def explode(arguments, context):
            raise RuntimeError("secret internal failure")

        monkeypatch.setattr(config, "TOOL_DEBUG_ERRORS", True)
        monkeypatch.setitem(TOOL_HANDLERS, "explode", explode)

        with pytest.raises(RuntimeError, match="secret internal failure"):
            run_tool("explode", {}, tool_use_id="t9")

    def test_tool_use_id_round_trips(self):
        result = run_tool("list_kb", {"subdir": ""}, tool_use_id="my-unique-id")
        assert result.tool_use_id == "my-unique-id"


# --------------------------------------------------------------------------- #
# SCHEMAS sanity
# --------------------------------------------------------------------------- #

class TestSchemas:
    def test_all_schemas_have_required_fields(self):
        for s in SCHEMAS:
            assert s["name"]
            assert s["description"]
            assert "input_schema" in s
            assert s["input_schema"]["type"] == "object"
            assert "properties" in s["input_schema"]
            assert "required" in s["input_schema"]

    def test_schema_names_match_dispatcher(self):
        # Every declared schema must dispatch successfully (or fail on missing args, but not "unknown tool").
        for s in SCHEMAS:
            result = run_tool(s["name"], {}, tool_use_id="schema-check")
            payload = json.loads(result.content)
            if result.is_error:
                # Acceptable: missing required arg. NOT acceptable: "unknown tool".
                assert "unknown tool" not in payload.get("error", "")


# --------------------------------------------------------------------------- #
# web_search
# --------------------------------------------------------------------------- #

class _StubResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FetchResponse:
    def __init__(
        self,
        status_code: int = 200,
        *,
        text: str = "",
        content_type: str = "text/html; charset=utf-8",
        url: str = "https://example.com/page",
        headers: dict | None = None,
    ):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.url = url
        self.headers = {"content-type": content_type, **(headers or {})}


class TestWebSearch:
    def test_dispatch_success(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "fake-key")
        captured: dict = {}

        def fake_post(url, json, timeout):  # noqa: A002
            captured["url"] = url
            captured["json"] = json
            return _StubResponse(
                200,
                {
                    "query": "fastapi sse",
                    "answer": "Server-Sent Events in FastAPI use StreamingResponse.",
                    "results": [
                        {
                            "title": "FastAPI docs",
                            "url": "https://fastapi.tiangolo.com/",
                            "content": "SSE example...",
                            "score": 0.91,
                        }
                    ],
                },
            )

        import backend.web_search as ws
        monkeypatch.setattr(ws.httpx, "post", fake_post)

        result = run_tool(
            "web_search",
            {"query": "fastapi sse", "max_results": 3},
            tool_use_id="ws1",
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["query"] == "fastapi sse"
        assert body["results"][0]["url"] == "https://fastapi.tiangolo.com/"
        assert captured["url"].startswith("https://api.tavily.com/")
        assert captured["json"]["api_key"] == "fake-key"
        assert captured["json"]["max_results"] == 3
        assert result.source_summary == "searched public web, 1 result"
        assert result.source_items == [
            {"label": "Web result: fastapi.tiangolo.com", "kind": "web"}
        ]

    def test_missing_api_key_returns_is_error(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        result = run_tool("web_search", {"query": "anything"}, tool_use_id="ws2")
        assert result.is_error is True
        assert "TAVILY_API_KEY" in json.loads(result.content)["error"]

    def test_empty_query_returns_is_error(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "fake-key")
        result = run_tool("web_search", {"query": "  "}, tool_use_id="ws3")
        assert result.is_error is True

    def test_http_error_surfaced(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "fake-key")

        def fake_post(url, json, timeout):  # noqa: A002
            return _StubResponse(429, text="rate limit")

        import backend.web_search as ws
        monkeypatch.setattr(ws.httpx, "post", fake_post)

        result = run_tool("web_search", {"query": "x"}, tool_use_id="ws4")
        assert result.is_error is True
        assert "rate limited" in json.loads(result.content)["error"].lower()

    def test_max_results_clamped(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "fake-key")
        captured: dict = {}

        def fake_post(url, json, timeout):  # noqa: A002
            captured["json"] = json
            return _StubResponse(200, {"query": "x", "answer": "", "results": []})

        import backend.web_search as ws
        monkeypatch.setattr(ws.httpx, "post", fake_post)

        run_tool("web_search", {"query": "x", "max_results": 999}, tool_use_id="ws5")
        assert captured["json"]["max_results"] == 10

    def test_blocked_when_not_in_allowlist(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "fake-key")
        result = run_tool(
            "web_search",
            {"query": "x"},
            tool_use_id="ws6",
            allowed_tools=("read_file",),
        )
        assert result.is_error is True
        assert "not enabled" in json.loads(result.content)["error"]


# --------------------------------------------------------------------------- #
# fetch_url_text
# --------------------------------------------------------------------------- #

class TestFetchUrlText:
    def test_fetches_public_text_page(self, monkeypatch):
        import backend.tools as tools

        monkeypatch.setattr(
            tools.socket,
            "getaddrinfo",
            lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))],
        )
        monkeypatch.setattr(
            tools.httpx,
            "get",
            lambda *args, **kwargs: _FetchResponse(
                text="<html><head><title>Example Title</title></head><body><h1>Hello</h1><p>World</p></body></html>"
            ),
        )

        result = run_tool(
            "fetch_url_text",
            {"url": "https://example.com/page", "max_chars": 40},
            tool_use_id="fetch1",
        )

        assert result.is_error is False
        body = json.loads(result.content)
        assert body["title"] == "Example Title"
        assert "Hello World" in body["excerpt"]
        assert body["content_type"] == "text/html"
        assert result.source_summary == "fetched public web page"
        assert result.source_items == [
            {"label": "Public web page: example.com", "kind": "web_fetch"}
        ]

    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://10.0.0.5/private",
            "http://169.254.169.254/latest/meta-data",
        ],
    )
    def test_rejects_unsafe_urls(self, url):
        result = run_tool("fetch_url_text", {"url": url}, tool_use_id="fetch2")
        assert result.is_error is True

    def test_rejects_non_text_content(self, monkeypatch):
        import backend.tools as tools

        monkeypatch.setattr(
            tools.socket,
            "getaddrinfo",
            lambda host, port: [(None, None, None, None, ("93.184.216.34", 0))],
        )
        monkeypatch.setattr(
            tools.httpx,
            "get",
            lambda *args, **kwargs: _FetchResponse(
                text="not really an image",
                content_type="image/png",
            ),
        )

        result = run_tool("fetch_url_text", {"url": "https://example.com/image"}, tool_use_id="fetch3")
        assert result.is_error is True
        assert "non-text" in json.loads(result.content)["error"]


# --------------------------------------------------------------------------- #
# calculator
# --------------------------------------------------------------------------- #

class TestCalculator:
    @pytest.mark.parametrize(
        ("operation", "values", "expected"),
        [
            ("sum", [1, 2, 3], 6),
            ("average", [2, 4, 6], 4),
            ("difference", [5, 9], 4),
            ("ratio", [4, 10], 2.5),
            ("percent_change", [100, 125], 25),
            ("cagr", [100, 121, 2], 10),
        ],
    )
    def test_supported_operations(self, operation, values, expected):
        result = run_tool(
            "calculator",
            {"operation": operation, "values": values},
            tool_use_id=f"calc-{operation}",
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["result"] == pytest.approx(expected)
        assert result.source_summary == "calculated result"

    def test_rejects_arbitrary_expression(self):
        result = run_tool(
            "calculator",
            {"operation": "eval", "values": [1]},
            tool_use_id="calc-bad",
        )
        assert result.is_error is True
        assert "unsupported" in json.loads(result.content)["error"]


# --------------------------------------------------------------------------- #
# Sales preview tools
# --------------------------------------------------------------------------- #

class TestSalesPreviewTools:
    def sales_data_root(self):
        profile = load_profile("sales-concierge")
        assert profile.data_root is not None
        return profile.data_root

    def test_catalog_lookup_reads_profile_catalog(self):
        result = run_tool(
            "catalog_lookup",
            {"query": "sales checkout lead", "max_results": 2},
            tool_use_id="catalog1",
            data_root=self.sales_data_root(),
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["matches"][0]["id"] == "sales-profile"
        assert body["matches"][0]["price_display"]
        assert result.source_items == [{"label": "Product catalog", "kind": "catalog"}]

    def test_qualify_lead_is_deterministic(self):
        result = run_tool(
            "qualify_lead",
            {
                "use_case": "We need sales lead qualification with Stripe checkout",
                "urgency": "urgent this week",
                "team_size": "5",
                "budget_range": "approved 10k",
                "integrations": ["Stripe", "CRM"],
            },
            tool_use_id="qual1",
            data_root=self.sales_data_root(),
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["tier"] == "high"
        assert body["recommended_package_id"] == "sales-profile"
        assert body["preview_only"] is True

    def test_lead_capture_preview_does_not_persist(self):
        result = run_tool(
            "lead_capture_preview",
            {
                "name": "Ada Lovelace",
                "email": "Ada@Example.com",
                "company": "Analytical Engines",
                "use_case": "sales concierge",
                "notes": "preview only",
            },
            tool_use_id="lead1",
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["mock_lead_id"].startswith("lead_preview_")
        assert body["payload"]["email"] == "ada@example.com"
        assert body["persisted"] is False
        assert body["preview_only"] is True

    def test_checkout_link_preview_does_not_call_stripe(self):
        result = run_tool(
            "checkout_link_preview",
            {"package_id": "starter-widget", "billing_cadence": "one_time", "quantity": 2},
            tool_use_id="checkout1",
            data_root=self.sales_data_root(),
        )
        assert result.is_error is False
        body = json.loads(result.content)
        assert body["checkout_url"].startswith("https://checkout.example/preview/")
        assert body["line_items"][0]["quantity"] == 2
        assert body["stripe_session_created"] is False
        assert body["preview_only"] is True

    def test_sales_tools_require_data_root(self):
        result = run_tool(
            "catalog_lookup",
            {"query": "sales"},
            tool_use_id="catalog-missing-root",
        )
        assert result.is_error is True
        assert "data_root" in json.loads(result.content)["error"]


# --------------------------------------------------------------------------- #
# Engine vs. personal-site decoupling
# --------------------------------------------------------------------------- #

def _profile(kb_root, *, source_path_labels=(), source_labels=None):
    return AgentProfile(
        id="p",
        label="P",
        description="",
        kb_root=kb_root,
        system_prompt="s",
        source_labels=source_labels or {},
        source_path_labels=tuple(source_path_labels),
    )


class TestEngineDecoupling:
    def test_personal_tools_not_in_defaults(self):
        assert DEFAULT_PROFILE_TOOLS == ("list_kb", "read_file", "search_kb", "web_search")
        assert "get_resume_summary" not in DEFAULT_PROFILE_TOOLS
        assert "get_project_context" not in DEFAULT_PROFILE_TOOLS

    def test_personal_tools_still_globally_registered(self):
        # Moved to personal_kb.py, but a profile can still opt in by listing them.
        assert "get_resume_summary" in TOOL_DEFS_BY_NAME
        assert "get_project_context" in TOOL_DEFS_BY_NAME


class TestProfileScopedSourceLabels:
    def test_profile_path_labels_apply(self, kb_root):
        profile = _profile(
            kb_root,
            source_path_labels=[
                ("resume/resume.md", "Resume"),
                ("meta/", "Portfolio knowledge base"),
            ],
        )
        r = run_tool("read_file", {"path": "meta/faq.md"}, "t1", root=kb_root, profile=profile)
        assert r.source_items == [{"label": "Portfolio knowledge base", "kind": "kb_read"}]
        r2 = run_tool("read_file", {"path": "resume/resume.md"}, "t2", root=kb_root, profile=profile)
        assert r2.source_items == [{"label": "Resume", "kind": "kb_read"}]

    def test_generic_profile_gets_generic_label(self, kb_root):
        # No source_path_labels: the engine carries no personal taxonomy.
        profile = _profile(kb_root)
        r = run_tool("read_file", {"path": "meta/faq.md"}, "t", root=kb_root, profile=profile)
        assert r.source_items == [{"label": "Knowledge base document", "kind": "kb_read"}]

    def test_projects_slug_is_generic_engine_rule(self, kb_root):
        # projects/<slug> -> "Project: <Title>" stays a data-derived engine rule.
        profile = _profile(kb_root)
        r = run_tool("read_file", {"path": "projects/widget.md"}, "t", root=kb_root, profile=profile)
        assert r.source_items == [{"label": "Project: Widget", "kind": "kb_read"}]


class TestMetadataBuilderArity:
    def test_every_builder_accepts_tool_context(self):
        # Guards the (args, out, ToolContext) signature: a builder left at arity
        # 2 would TypeError here. None output exercises the empty-result path.
        ctx = ToolContext()
        for tool in TOOL_DEFS:
            meta = tool.source_metadata({}, None, ctx)
            assert {"source_summary", "source_items", "source_count", "hidden_count"} <= set(meta)
