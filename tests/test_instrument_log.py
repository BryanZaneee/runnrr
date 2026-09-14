"""Coverage for `_instrument`, the per-turn structured record.

`chat_complete` was previously untested despite being the only per-turn
observability we have — and the numbers in it were wrong. These tests are the
regression net for the caching and interop work that follows, both of which are
judged by reading these fields back.
"""
from __future__ import annotations

import logging

import pytest


def _chat_complete(caplog) -> logging.LogRecord:
    records = [r for r in caplog.records if r.msg == "chat_complete"]
    assert len(records) == 1, f"expected one chat_complete, got {len(records)}"
    return records[0]


def _run_turn(c, app_module, monkeypatch, fake_provider_cls, hops, session="log1"):
    fake = fake_provider_cls(hops)
    monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
    with c.stream(
        "POST",
        "/api/chat",
        json={"session_id": session, "message": "hi", "model": "claude-sonnet-4-5"},
    ) as r:
        b"".join(r.iter_bytes())


TEXT_HOP = [
    {"type": "text_delta", "text": "Hello"},
    {"type": "usage", "usage": {
        "input_tokens": 100,
        "output_tokens": 20,
        "reasoning_tokens": 5,
        "cache_read_input_tokens": 60,
        "cache_creation_input_tokens": 10,
    }},
    {"type": "message_done", "stop_reason": "end_turn"},
]


class TestChatCompleteFields:
    def test_emits_the_new_fields(self, client, monkeypatch, fake_provider_cls, caplog):
        c, app_module = client
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(c, app_module, monkeypatch, fake_provider_cls, [TEXT_HOP])

        rec = _chat_complete(caplog)
        assert len(rec.turn_id) == 12
        assert rec.ttft_ms is not None and rec.ttft_ms >= 0
        assert rec.hops == 1
        assert rec.tool_calls == 0
        assert rec.status == "ok"
        assert rec.error_class is None
        assert rec.usage_estimated is False

    def test_reasoning_is_charged_to_the_budget(
        self, client, monkeypatch, fake_provider_cls, caplog
    ):
        # The old total was input + output, so thinking tokens were billed by the
        # vendor and free here.
        c, app_module = client
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(c, app_module, monkeypatch, fake_provider_cls, [TEXT_HOP])

        rec = _chat_complete(caplog)
        assert rec.tokens_reasoning == 5
        assert rec.tokens_total == 100 + 20 + 5

    def test_cache_fields_are_not_added_to_the_total(
        self, client, monkeypatch, fake_provider_cls, caplog
    ):
        # They are subsets of input_tokens; adding them would double-count.
        c, app_module = client
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(c, app_module, monkeypatch, fake_provider_cls, [TEXT_HOP])

        rec = _chat_complete(caplog)
        assert rec.cache_read == 60
        assert rec.cache_write == 10
        assert rec.tokens_total == 125

    def test_budget_records_the_same_total(
        self, client, monkeypatch, fake_provider_cls, caplog
    ):
        c, app_module = client
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(c, app_module, monkeypatch, fake_provider_cls, [TEXT_HOP])

        rec = _chat_complete(caplog)
        assert app_module.TOKEN_BUDGET.stats()["used"] == rec.tokens_total

    def test_unpriced_model_logs_null_cost(
        self, client, monkeypatch, fake_provider_cls, caplog
    ):
        # claude-sonnet-4-5 has no pricing entry yet. It must log null, never 0.0 —
        # a zero would read as a free turn.
        c, app_module = client
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(c, app_module, monkeypatch, fake_provider_cls, [TEXT_HOP])

        assert _chat_complete(caplog).cost_usd is None


class TestHopAndToolCounting:
    def test_hops_counts_hops_not_tool_calls(
        self, client, monkeypatch, fake_provider_cls, caplog
    ):
        """One hop calling two tools is 1 hop and 2 tool calls.

        The old `tool_hops` counted `tool_use_start` events, so this case logged
        2 "hops" — and because two providers dedupe that event by tool name, the
        same workload logged different numbers depending on the provider.
        """
        c, app_module = client
        tool_hop = [
            {"type": "tool_use_start", "name": "list_kb"},
            {"type": "tool_use_complete", "tool_use_id": "t1", "name": "list_kb", "arguments": {}},
            {"type": "tool_use_start", "name": "list_kb"},
            {"type": "tool_use_complete", "tool_use_id": "t2", "name": "list_kb", "arguments": {}},
            {"type": "usage", "usage": {"input_tokens": 10, "output_tokens": 2}},
            {"type": "message_done", "stop_reason": "tool_use"},
        ]
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(
                c, app_module, monkeypatch, fake_provider_cls, [tool_hop, TEXT_HOP]
            )

        rec = _chat_complete(caplog)
        assert rec.hops == 2
        assert rec.tool_calls == 2

    def test_tool_hops_alias_is_preserved(
        self, client, monkeypatch, fake_provider_cls, caplog
    ):
        # chat_complete has an out-of-repo consumer; fields are added, not renamed.
        c, app_module = client
        with caplog.at_level(logging.INFO, logger="runnrr"):
            _run_turn(c, app_module, monkeypatch, fake_provider_cls, [TEXT_HOP])
        assert hasattr(_chat_complete(caplog), "tool_hops")


class TestToolTiming:
    def test_tool_result_frame_carries_duration(
        self, client, monkeypatch, fake_provider_cls, parse_sse
    ):
        c, app_module = client
        tool_hop = [
            {"type": "tool_use_start", "name": "list_kb"},
            {"type": "tool_use_complete", "tool_use_id": "t1", "name": "list_kb", "arguments": {}},
            {"type": "usage", "usage": {"input_tokens": 10, "output_tokens": 2}},
            {"type": "message_done", "stop_reason": "tool_use"},
        ]
        fake = fake_provider_cls([tool_hop, TEXT_HOP])
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
        with c.stream(
            "POST",
            "/api/chat",
            json={"session_id": "td1", "message": "hi", "model": "claude-sonnet-4-5"},
        ) as r:
            body = b"".join(r.iter_bytes()).decode("utf-8")

        results = [d for kind, d in parse_sse(body) if kind == "tool_result"]
        assert results, "no tool_result frame"
        assert results[0]["duration_ms"] is not None
        assert results[0]["duration_ms"] >= 0

    def test_usage_event_carries_hop_ms(
        self, client, monkeypatch, fake_provider_cls, parse_sse
    ):
        c, app_module = client
        fake = fake_provider_cls([TEXT_HOP])
        monkeypatch.setattr(app_module, "get_provider", lambda mid: fake)
        with c.stream(
            "POST",
            "/api/chat",
            json={"session_id": "hm1", "message": "hi", "model": "claude-sonnet-4-5"},
        ) as r:
            body = b"".join(r.iter_bytes()).decode("utf-8")

        usages = [d for kind, d in parse_sse(body) if kind == "usage"]
        assert usages and usages[0]["hop_ms"] >= 0
