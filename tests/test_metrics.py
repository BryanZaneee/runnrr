"""Metrics use provider reports, preserve unknowns, and never persist conversation content."""

import json
import sqlite3
from datetime import date

import pytest

from runnrr import metrics
from runnrr.pricing import cache_savings_usd, cost_breakdown, cost_usd
from runnrr.usage import billable_total


async def instrument(events, **kwargs):
    from runnrr.app import _instrument

    async def stream():
        for event in events:
            yield event

    return [
        event
        async for event in _instrument(
            stream(),
            ip="private-ip",
            session_id="private-session",
            model_id="claude-haiku-4-5",
            profile_id="research-analyst",
            turn_id="turn-one",
            **kwargs,
        )
    ]


@pytest.mark.asyncio
async def test_multihop_metrics_and_durable_history():
    events = [
        {"event": "model_start", "hop": 0},
        {"event": "thinking_delta", "text": "private thinking"},
        {
            "event": "usage",
            "input_tokens": 100,
            "output_tokens": 30,
            "reasoning_tokens": 20,
            "cache_read_input_tokens": 60,
            "cache_creation_input_tokens": 10,
            "reasoning_estimated": True,
        },
        {"event": "tool_result", "is_error": True, "source_summary": "private tool output"},
        {"event": "model_start", "hop": 1},
        {"event": "delta", "text": "private answer"},
        {"event": "usage", "input_tokens": 150, "output_tokens": 50, "reasoning_tokens": 10},
        {"event": "done"},
    ]
    out = await instrument(events)
    m = out[-2]
    assert m["event"] == "metrics" and out[-1]["event"] == "done"
    assert m["usage_version"] == 2
    assert m["tokens_total"] == 330
    assert m["tokens"]["reasoning"] == 30
    assert m["context_tokens"] == 150  # latest input, never summed inputs
    assert m["hops"] == 2 and m["tool_calls"] == 1 and m["tool_errors"] == 1
    assert m["usage_status"] == "complete" and m["reasoning_estimated"]
    assert m["first_text_ms"] >= m["ttft_ms"] >= 0
    assert m["cost_usd"] == cost_usd(m["model"], m["tokens"])
    assert sum(m["category_cost_usd"].values()) == pytest.approx(m["cost_usd"])
    assert m["cache_savings_usd"] == pytest.approx(0.000054)
    today = date.fromisoformat(m["started_at"][:10])
    # Reopen independent connections, like a restart, and dedupe the same turn.
    metrics.record({k: v for k, v in m.items() if k != "event"}, "private-session")
    result = metrics.summary(today, today)
    assert result["totals"]["tokens_total"] == 330
    assert result["totals"]["turns"] == result["totals"]["sessions"] == 1
    assert result["providers"][0]["label"] == "Anthropic"
    with metrics.connection() as conn:
        raw = json.dumps([list(row) for row in conn.execute("SELECT * FROM usage_turns")])
    assert "private" not in raw
    assert "session_hash" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("ending,status", [("done", "ok"), ("error", "error")])
async def test_missing_usage_is_unavailable_not_free(ending, status):
    out = await instrument([{"event": "model_start"}, {"event": ending}])
    m = out[-2]
    assert m["usage_status"] == "unavailable"
    assert m["cost_usd"] is None and m["context_tokens"] is None
    assert m["ttft_ms"] is None and m["status"] == status


@pytest.mark.asyncio
async def test_missing_hop_and_failure_are_partial():
    for terminal in ("done", "error"):
        out = await instrument(
            [
                {"event": "model_start"},
                {"event": "usage", "input_tokens": 10, "output_tokens": 5},
                {"event": "model_start"},
                {"event": terminal},
            ]
        )
        assert out[-2]["usage_status"] == "partial"
        assert out[-2]["tokens_total"] == 15


@pytest.mark.asyncio
async def test_closed_stream_is_recorded_as_interrupted():
    from runnrr.app import _instrument

    async def events():
        yield {"event": "model_start"}
        yield {"event": "usage", "input_tokens": 10, "output_tokens": 5}
        yield {"event": "done"}

    stream = _instrument(
        events(),
        ip="ip",
        session_id="session",
        model_id="gpt-5",
        profile_id="research-analyst",
        turn_id="closed",
    )
    await anext(stream)
    await anext(stream)
    await stream.aclose()
    with metrics.connection() as conn:
        m = json.loads(conn.execute("SELECT metrics FROM usage_turns").fetchone()[0])
    assert m["status"] == "interrupted" and m["usage_status"] == "partial"
    assert m["tokens_total"] == 15 and m["cost_usd"] is None


def make_record(turn, day, model="claude-haiku-4-5", priced=True):
    tokens = {"input": 100, "output": 20, "reasoning": 5, "cache_read": 60, "cache_write": 10}
    return dict(
        turn_id=turn,
        started_at=f"{day}T00:00:00+00:00",
        model=model,
        provider="Anthropic",
        profile="research-analyst",
        tokens=tokens,
        tokens_total=billable_total(tokens),
        cost_usd=cost_usd(model, tokens) if priced else None,
        category_cost_usd=cost_breakdown(model, tokens) if priced else None,
        cache_savings_usd=cache_savings_usd(model, tokens) if priced else None,
        usage_status="complete",
        status="ok",
        usage_estimated=False,
        reasoning_estimated=False,
        duration_ms=200,
        ttft_ms=50,
        hops=1,
        tool_calls=0,
        tool_errors=0,
    )


def test_aggregation_filters_mixed_prices_and_unique_sessions(client):
    c, _ = client
    metrics.record(make_record("one", "2026-10-15"), "session")
    metrics.record(make_record("two", "2026-10-16", "gpt-5", False), "session")
    metrics.record(make_record("old", "2026-09-01"), "other")
    result = c.get("/api/usage?since=2026-10-15&until=2026-10-16").json()
    totals = result["totals"]
    assert totals["turns"] == 2 and totals["sessions"] == 1
    assert totals["tokens_total"] == 240
    assert totals["cost_usd"] is None and totals["known_cost_usd"] > 0
    assert totals["unpriced_turns"] == 1 and totals["cache_hit_rate"] == 0.6
    assert len(result["days"]) == len(result["models"]) == 2
    filtered = c.get("/api/usage?since=2026-10-15&until=2026-10-16&model=gpt-5").json()
    assert filtered["totals"]["turns"] == 1 and filtered["totals"]["cost_usd"] is None
    empty = c.get("/api/usage?profile=missing").json()["totals"]
    assert empty["turns"] == 0 and empty["cache_hit_rate"] is None
    assert empty["avg_ttft_ms"] is None
    for query in ("since=2026-10-17&until=2026-10-16", "since=2020-01-01", "since=bad"):
        assert c.get("/api/usage?" + query).status_code == 422


@pytest.mark.asyncio
async def test_storage_failure_does_not_break_chat(client, monkeypatch, caplog):
    def fail(*args):
        raise sqlite3.OperationalError("disk unavailable")

    monkeypatch.setattr(metrics, "record", fail)
    out = await instrument([{"event": "done"}])
    assert out[-1]["event"] == "done"
    assert "usage history write failed" in caplog.text
    monkeypatch.setattr(metrics, "summary", fail)
    assert client[0].get("/api/usage").status_code == 503
