"""Deterministic fake LLM transport (SPY_HUNT_FAKE_LLM=1). No network.

Later tasks register canned outputs: register("bot", lambda prompt: '{"text": "hi"}').
A factory returns a JSON string (or a dict, which is dumped). Unknown task -> LlmError.
"""
from __future__ import annotations

import json
from typing import Callable, Dict, Union

_registry: Dict[str, Callable[[str], Union[str, dict]]] = {}


def register(task: str, factory: Callable[[str], Union[str, dict]]) -> None:
    _registry[task] = factory


def reset() -> None:
    _registry.clear()


def complete(task: str, prompt: str, max_tokens: int, timeout: float) -> str:
    factory = _registry.get(task)
    if factory is None:
        from .llm import LlmError
        raise LlmError(f"no fake response registered for task {task!r}")
    out = factory(prompt)
    return out if isinstance(out, str) else json.dumps(out)
