from concurrent.futures import ThreadPoolExecutor

import pytest

from runnrr.budget import BudgetExhausted, TokenBudget


def test_reservations_survive_restart_and_concurrency(tmp_path):
    path = tmp_path / "budget.sqlite"

    def attempt(_):
        try:
            TokenBudget(100, path).reserve(30)
            return 1
        except BudgetExhausted:
            return 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 3
    assert TokenBudget(100, path).stats()["used"] == 90


def test_settlement_charges_original_day(tmp_path, monkeypatch):
    budget = TokenBudget(100, tmp_path / "budget.sqlite")
    monkeypatch.setattr(budget, "_today", lambda: "2026-10-04")
    day = budget.reserve(100)
    monkeypatch.setattr(budget, "_today", lambda: "2026-10-05")
    budget.reserve(80)
    budget.settle(day, 100, 30)
    assert budget.stats()["used"] == 80
    monkeypatch.setattr(budget, "_today", lambda: day)
    assert budget.stats()["used"] == 30


def test_unavailable_store_denies_reservation(tmp_path):
    path = tmp_path / "blocked"
    path.write_text("not a database")
    budget = TokenBudget(100, path)
    assert not budget.has_capacity()
    with pytest.raises(BudgetExhausted):
        budget.reserve(1)


@pytest.mark.asyncio
async def test_exhaustion_prevents_provider_call(monkeypatch, fake_provider_cls):
    from runnrr.agent import run_conversation_stream
    from runnrr.budget import TOKEN_BUDGET

    monkeypatch.setattr(TOKEN_BUDGET, "daily_limit", 1)
    provider = fake_provider_cls([])
    called = False

    async def stream(**kwargs):
        nonlocal called
        called = True
        yield {"type": "message_done"}

    monkeypatch.setattr(provider, "stream", stream)
    events = [
        event
        async for event in run_conversation_stream(
            "hello", {"messages": []}, provider, "test-model"
        )
    ]
    assert not called
    assert events[-1]["event"] == "error"


@pytest.mark.asyncio
async def test_failed_call_retains_reservation(fake_provider_cls):
    from runnrr.agent import run_conversation_stream
    from runnrr.budget import TOKEN_BUDGET

    provider = fake_provider_cls([[{"type": "error", "text": "timeout"}]])
    events = [
        event
        async for event in run_conversation_stream(
            "hello", {"messages": []}, provider, "test-model"
        )
    ]
    assert events[-1]["event"] == "error"
    assert TOKEN_BUDGET.stats()["used"] > 0


@pytest.mark.asyncio
async def test_gemini_typed_messages_can_be_reserved(monkeypatch):
    from runnrr.agent import run_conversation_stream
    from runnrr.providers.gemini_provider import GeminiProvider

    provider = GeminiProvider(client=object())
    called = False

    async def stream(**kwargs):
        nonlocal called
        called = True
        yield {"type": "message_done", "stop_reason": "end_turn"}

    monkeypatch.setattr(provider, "stream", stream)
    events = [
        event
        async for event in run_conversation_stream(
            "hello", {"messages": []}, provider, "gemini-2.5-flash"
        )
    ]
    assert called
    assert not any(event["event"] == "error" for event in events)


def test_paid_budget_is_atomic_and_shared_by_operations(monkeypatch):
    from runnrr.budget import reserve_paid_call

    monkeypatch.setenv("DEMO_REQUEST_COST_BOUNDS", '{"a":100000,"b":100000}')

    def attempt(index):
        try:
            reserve_paid_call("a" if index % 2 else "b")
            return 1
        except BudgetExhausted:
            return 0

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 5
    with pytest.raises(BudgetExhausted):
        reserve_paid_call("a")


def test_unconfigured_price_stops_search_before_network(monkeypatch):
    from runnrr.web_search import web_search

    monkeypatch.setenv("TAVILY_API_KEY", "test")
    monkeypatch.delenv("DEMO_REQUEST_COST_BOUNDS", raising=False)

    def unexpected(*args, **kwargs):
        raise AssertionError("unbudgeted provider call")

    monkeypatch.setattr("httpx.post", unexpected)
    with pytest.raises(BudgetExhausted, match="spending bound"):
        web_search("test")
