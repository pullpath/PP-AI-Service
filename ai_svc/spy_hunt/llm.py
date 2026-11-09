"""LLM wrapper for spy-hunt: every AI feature goes through call_json.

SPIKE (Task 8, 5 tiny live calls, max_tokens<=30, deepseek-chat):
  * openai client -> https://api.deepseek.com, response_format json_object,
    timeout=8: 1 of 2 calls returned empty/non-JSON content (the known DeepSeek
    JSON-mode quirk; our retry-once covers it), the other ~690 ms parsed OK.
    timeout=0.001 raised APITimeoutError after ~35 ms (timeout is real).
  * agno 2.4.7 Agent(model=DeepSeek(...)).run: 2 of 2 returned parseable JSON
    text, ~1.7-1.9 s each (slower, extra framework layer, no per-request
    timeout I could verify cheaply).
  DECISION: plain openai client (JSON mode + native timeout, lower latency).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict

from pydantic import BaseModel, ValidationError

from . import store
from .config import GameConfig

log = logging.getLogger("spy_hunt.llm")

TASK_TIMEOUTS: Dict[str, float] = {
    "bot": 8.0,
    "translate": 8.0,
    "pair_generate": 20.0,
    "pair_validate": 20.0,
    "host": 8.0,
}
BASE_URL = "https://api.deepseek.com"


class LlmError(Exception):
    """Model call failed (transport, timeout, unparseable output)."""


class BudgetExceeded(Exception):
    """The room's AI call budget is used up. Distinct from LlmError."""


def _model() -> str:
    return os.environ.get("SPY_HUNT_MODEL", "deepseek-chat")


def budget_remaining(room_id: str) -> int:
    room = store.get_room(room_id)
    if room is None:
        return 0
    return max(0, GameConfig().room_ai_budget - int(room["ai_calls"] or 0))


def budget_fraction_left(room_id: str) -> float:
    total = GameConfig().room_ai_budget
    return budget_remaining(room_id) / total if total else 0.0


def _reserve(room_id: str) -> None:
    budget = GameConfig().room_ai_budget
    with store.tx(room_id) as conn:
        cur = conn.execute(
            "UPDATE rooms SET ai_calls = COALESCE(ai_calls, 0) + 1 "
            "WHERE id = ? AND COALESCE(ai_calls, 0) < ?", (room_id, budget))
        if cur.rowcount == 0:
            raise BudgetExceeded(f"room AI budget of {budget} used up")


def _transport(task: str, prompt: str, max_tokens: int, timeout: float) -> str:
    if os.environ.get("SPY_HUNT_FAKE_LLM") == "1":
        from . import fake_llm
        return fake_llm.complete(task, prompt, max_tokens, timeout)
    from dotenv import load_dotenv
    load_dotenv()
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not key:
        raise LlmError("DEEPSEEK_API_KEY not configured")
    from openai import OpenAI
    client = OpenAI(api_key=key, base_url=BASE_URL, timeout=timeout, max_retries=0)
    resp = client.chat.completions.create(
        model=_model(),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    return resp.choices[0].message.content or ""


def call_json(task: str, prompt: str, schema: type[BaseModel], room_id: str,
              max_tokens: int, timeout: float) -> BaseModel:
    last = "unknown"
    for attempt in (1, 2):
        _reserve(room_id)  # raises BudgetExceeded; counter untouched then
        t0 = time.monotonic()
        outcome = "ok"
        try:
            try:
                raw = _transport(task, prompt, max_tokens, timeout)
            except LlmError:
                outcome = "LlmError"
                raise
            except Exception as e:  # SDK/transport errors incl. timeouts
                outcome = type(e).__name__
                raise LlmError(f"model call failed: {outcome}") from None
            try:
                return schema.model_validate_json(raw)
            except (ValidationError, ValueError) as e:
                outcome = type(e).__name__
                last = outcome
        finally:
            log.info("llm call task=%s room_id=%s latency_ms=%d attempt=%d result=%s",
                     task, room_id, int((time.monotonic() - t0) * 1000), attempt, outcome)
    raise LlmError(f"model output failed validation twice ({last})")
