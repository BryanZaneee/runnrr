from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.profiles import ProfileConfigError, build_kb_manifest, load_profile
from backend.providers.gemini_provider import GeminiProvider
from backend.providers.openai_compat_provider import OpenAICompatProvider
from backend.tools import SCHEMAS, run_tool


class DummyClient:
    pass


async def collect(gen):
    return [ev async for ev in gen]


def test_personal_agent_profile_loads_persona_and_kb_root():
    profile = load_profile("personal-agent")
    assert profile.id == "personal-agent"
    assert profile.kb_root.name == "kb"
    assert "advocate-in-residence" in profile.system_prompt
    assert profile.label == "Personal Agent"
    assert "get_resume_summary" in profile.tools
    assert "Bryan's resume" in profile.tool_descriptions["get_resume_summary"]
    assert "Tell me about Shuttrr." in profile.suggestions
    # Personal Agent does not opt into manifest injection, so its system prompt is not augmented.
    assert "<knowledge_base_index>" not in profile.system_prompt


def test_frampton_profile_loads_ds1_persona_and_kb_tools():
    profile = load_profile("frampton")
    assert profile.id == "frampton"
    assert profile.label == "Frampton"
    assert "Dark Souls 1" in profile.description
    assert profile.kb_root.as_posix().endswith(
        ("kb/frampton", "dark_souls_1_fextra_kb_by_category")
    )
    assert "local Dark Souls 1 Fextralife knowledge base" in profile.system_prompt
    assert profile.tools == (
        "list_kb",
        "read_file",
        "search_kb",
        "semantic_search_kb",
    )
    assert "Artorias" in profile.suggestions[1]
    assert profile.brand["accent"] == "#B3261E"
    assert profile.brand["accent_dark"] == "#4A0F0B"
    assert profile.brand["accent_soft"] == "#F8D8D4"
    assert profile.brand["grid"] == "rgba(179, 38, 30, 0.14)"
    assert profile.brand["mark"] == "#E11D48"
    assert profile.brand["hero_icon"] == " /\\_/\\\n( o_o )\n/|___|\\\n  v v"
    assert profile.brand["input_placeholder"] == "ask Frampton about Dark Souls 1..."


def test_frampton_profile_prepends_kb_manifest():
    profile = load_profile("frampton")
    # Manifest is injected ahead of the persona block.
    assert profile.system_prompt.startswith("<knowledge_base_index>")
    assert "</knowledge_base_index>" in profile.system_prompt
    # Common categories appear in the index so the model knows where to look without list_kb.
    assert "Bosses/" in profile.system_prompt
    assert "Weapons/" in profile.system_prompt


def test_build_kb_manifest_on_mini_kb(kb_root):
    manifest = build_kb_manifest(kb_root)
    assert manifest.startswith("<knowledge_base_index>")
    assert manifest.endswith("</knowledge_base_index>")
    # Mini KB has INDEX.md at the top level and several markdown subdirs.
    assert "Top-level: INDEX" in manifest
    assert "projects/: widget" in manifest
    assert "resume/: resume" in manifest


def test_build_kb_manifest_on_missing_root_returns_empty(tmp_path):
    assert build_kb_manifest(tmp_path / "does-not-exist") == ""


def test_build_kb_manifest_skips_symlink_escape(tmp_path):
    kb = tmp_path / "kb"
    notes = kb / "notes"
    notes.mkdir(parents=True)
    (notes / "inside.md").write_text("inside", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("outside", encoding="utf-8")
    link = notes / "leak.md"
    try:
        link.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    manifest = build_kb_manifest(kb)

    assert "notes/: inside" in manifest
    assert "leak" not in manifest


def test_inject_kb_manifest_opt_in(tmp_path):
    """A profile only gets the manifest when it opts in via inject_kb_manifest."""
    profile_dir = tmp_path / "tinyprof"
    profile_dir.mkdir()
    kb_dir = tmp_path / "tinykb"
    kb_dir.mkdir()
    (kb_dir / "Notes").mkdir()
    (kb_dir / "Notes" / "alpha.md").write_text("alpha")

    (profile_dir / "system.md").write_text("you are a tiny agent")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "tinyprof",
                "label": "Tiny",
                "description": "test",
                "kb_root": str(kb_dir),
                "system_prompt_path": str(profile_dir / "system.md"),
                "tools": ["list_kb", "read_file", "search_kb"],
                "inject_kb_manifest": True,
            }
        )
    )

    profile = load_profile("tinyprof", profile_root=tmp_path)
    assert profile.system_prompt.startswith("<knowledge_base_index>")
    assert "Notes/: alpha" in profile.system_prompt
    assert "you are a tiny agent" in profile.system_prompt


def test_unknown_explicit_profile_raises():
    with pytest.raises(FileNotFoundError):
        load_profile("definitely-not-a-profile")


def test_unknown_tool_name_raises_profile_config_error(tmp_path):
    """A typo in a profile's tools list fails loudly instead of being silently dropped."""
    profile_dir = tmp_path / "typoprof"
    profile_dir.mkdir()
    (profile_dir / "system.md").write_text("you are a typo agent")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "typoprof",
                "label": "Typo",
                "description": "test",
                "system_prompt_path": str(profile_dir / "system.md"),
                "tools": ["list_kb", "serch_kb"],  # typo: serch_kb
            }
        )
    )
    with pytest.raises(ProfileConfigError) as excinfo:
        load_profile("typoprof", profile_root=tmp_path)
    assert "serch_kb" in str(excinfo.value)


def test_empty_tools_list_is_valid(tmp_path):
    """A profile with no tools is valid (closed-book / non-KB profiles)."""
    profile_dir = tmp_path / "noprof"
    profile_dir.mkdir()
    (profile_dir / "system.md").write_text("you have no tools")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "noprof",
                "label": "No Tools",
                "description": "test",
                "system_prompt_path": str(profile_dir / "system.md"),
                "tools": [],
            }
        )
    )
    profile = load_profile("noprof", profile_root=tmp_path)
    assert profile.tools == ()


def test_missing_default_profile_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_profile(profile_root=tmp_path)


def test_profile_without_tools_key_gets_generic_defaults(tmp_path):
    """A minimal profile.json must NOT silently inherit personal-site tools."""
    from backend.profiles import DEFAULT_PROFILE_TOOLS

    profile_dir = tmp_path / "barebones"
    profile_dir.mkdir()
    (profile_dir / "system.md").write_text("you are a barebones agent")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "barebones",
                "label": "Barebones",
                "description": "no tools key",
                "kb_root": str(tmp_path),
                "system_prompt_path": str(profile_dir / "system.md"),
            }
        )
    )

    profile = load_profile("barebones", profile_root=tmp_path)
    assert profile.tools == ("list_kb", "read_file", "search_kb", "web_search")
    assert profile.tools == DEFAULT_PROFILE_TOOLS
    assert "get_resume_summary" not in profile.tools
    assert "get_project_context" not in profile.tools


def test_model_registry_entries_expose_typed_public_fields():
    from backend.config import MODEL_REGISTRY, available_models

    cfg = MODEL_REGISTRY["claude-sonnet-4-5"]
    assert cfg["provider"] == "anthropic"
    assert cfg["model"] == "claude-sonnet-4-5"
    assert cfg["label"] == "Claude Sonnet 4.5"
    assert cfg["vendor"] == "Anthropic"

    listed = available_models()
    assert all({"id", "label", "vendor", "provider"} <= set(model) for model in listed)


def test_profile_parses_source_path_labels(tmp_path):
    profile_dir = tmp_path / "labeled"
    profile_dir.mkdir()
    (profile_dir / "system.md").write_text("agent")
    (profile_dir / "profile.json").write_text(
        json.dumps(
            {
                "id": "labeled",
                "label": "Labeled",
                "description": "path labels",
                "kb_root": str(tmp_path),
                "system_prompt_path": str(profile_dir / "system.md"),
                "source_path_labels": [
                    ["docs/menu.md", "Menu"],
                    ["policies/", "Store policy"],
                    "malformed-entry-ignored",
                ],
            }
        )
    )

    profile = load_profile("labeled", profile_root=tmp_path)
    # Case-sensitive, ordered, malformed entries dropped.
    assert profile.source_path_labels == (
        ("docs/menu.md", "Menu"),
        ("policies/", "Store policy"),
    )


def test_tool_allowlist_blocks_disabled_tool(kb_root):
    result = run_tool(
        "get_resume_summary",
        {},
        "toolu_disabled",
        root=kb_root,
        allowed_tools=("list_kb",),
    )
    assert result.is_error is True
    assert "not enabled" in result.content


def test_openai_compat_provider_uses_translated_tools_without_client_key():
    provider = OpenAICompatProvider(api_key_env="NO_SUCH_KEY", client=DummyClient())
    tools = provider.tools_for_provider(load_profile("personal-agent"))
    assert tools[0]["type"] == "function"


def test_gemini_provider_builds_function_declarations_without_client_key():
    provider = GeminiProvider(client=DummyClient())
    tools = provider.tools_for_provider(load_profile("personal-agent"))
    declarations = tools[0].function_declarations
    assert declarations[0].name == SCHEMAS[0]["name"]
    assert declarations[0].parameters_json_schema == SCHEMAS[0]["input_schema"]


class FakeAsyncStream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


class FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks
        self.request = None

    async def create(self, **request):
        self.request = request
        return FakeAsyncStream(self.chunks)


class FakeOpenAIClient:
    def __init__(self, chunks):
        self.completions = FakeCompletions(chunks)
        self.chat = SimpleNamespace(completions=self.completions)


@pytest.mark.asyncio
async def test_openai_provider_accumulates_streaming_tool_call():
    chunks = [
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(content="I'll check.", tool_calls=None),
                )
            ],
        ),
        SimpleNamespace(
            usage=None,
            choices=[
                SimpleNamespace(
                    finish_reason=None,
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id="call_1",
                                type="function",
                                function=SimpleNamespace(
                                    name="get_resume_summary",
                                    arguments="",
                                ),
                            )
                        ],
                    ),
                )
            ],
        ),
        SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            choices=[
                SimpleNamespace(
                    finish_reason="tool_calls",
                    delta=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                index=0,
                                id=None,
                                type=None,
                                function=SimpleNamespace(name=None, arguments="{}"),
                            )
                        ],
                    ),
                )
            ],
        ),
    ]
    client = FakeOpenAIClient(chunks)
    provider = OpenAICompatProvider(api_key_env="NO_SUCH_KEY", client=client)
    profile = load_profile("personal-agent")
    messages = [provider.format_user("resume?")]

    events = await collect(
        provider.stream(
            model="gpt-test",
            messages=messages,
            system=provider.system_for_provider(profile),
            tools=provider.tools_for_provider(profile),
            max_tokens=128,
        )
    )

    assert client.completions.request["stream"] is True
    assert messages[-1]["tool_calls"][0]["id"] == "call_1"
    assert any(e["type"] == "tool_use_start" for e in events)
    complete = [e for e in events if e["type"] == "tool_use_complete"][0]
    assert complete["tool_use_id"] == "call_1"
    assert complete["arguments"] == {}
    assert events[-1] == {"type": "message_done", "stop_reason": "tool_use"}
