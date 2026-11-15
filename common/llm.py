"""Model routing, prompt loading, caching and token/cost accounting.

* Every node's model comes from agent/config.yaml (profile x tier), never from code.
* Prompts are versioned markdown files in agent/prompts/ (no inline prompts).
* Calls are cached in SQLite (keyed by model + prompt) - this is also one of the measured optimisations.
* Cheap nodes get a fallback model; failures surface as LLMUnavailable so callers can degrade to rules.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from string import Template
from typing import Any

import yaml

from common import config as cfg

PROMPT_DIR = cfg.ROOT / "agent" / "prompts"


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_s: float = 0.0
    cached: bool = False
    cost_usd: float = 0.0
    prompt_version: str = ""

    def usage(self, node: str) -> dict[str, Any]:
        return {"node": node, "model": self.model, "in": self.input_tokens, "out": self.output_tokens,
                "latency_s": round(self.latency_s, 3), "cached": self.cached, "usd": round(self.cost_usd, 6),
                "prompt_version": self.prompt_version}


# ----------------------------------------------------------------------------- prompts
@dataclass
class Prompt:
    name: str
    version: str
    system: str
    user: str
    meta: dict = field(default_factory=dict)

    def render(self, **kw: Any) -> tuple[str, str]:
        return Template(self.system).safe_substitute(**kw), Template(self.user).safe_substitute(**kw)


@lru_cache(maxsize=64)
def load_prompt(name: str) -> Prompt:
    raw = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    meta = yaml.safe_load(m.group(1)) if m else {}
    body = m.group(2) if m else raw
    parts = re.split(r"^## (system|user)\s*$", body, flags=re.M)
    sec = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return Prompt(name, str(meta.get("version", "0")), sec.get("system", ""), sec.get("user", ""), meta)


# ----------------------------------------------------------------------------- cache
class _Cache:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT)")
        self.lock = threading.Lock()

    def get(self, k: str) -> dict | None:
        with self.lock:
            r = self.db.execute("SELECT v FROM c WHERE k=?", (k,)).fetchone()
        return json.loads(r[0]) if r else None

    def put(self, k: str, v: dict) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO c VALUES (?,?)", (k, json.dumps(v)))
            self.db.commit()


@lru_cache(maxsize=1)
def _cache() -> _Cache:
    return _Cache(Path(os.environ.get("LLM_CACHE_PATH", cfg.ROOT / "data" / "processed" / "llm_cache.sqlite")))


# ----------------------------------------------------------------------------- models
def profile() -> dict[str, Any]:
    name = cfg.get("models.profile", "open")
    return {"name": name, **cfg.get(f"models.profiles.{name}")}


def model_for(node: str, tier: str | None = None) -> tuple[str, str]:
    p = profile()
    tier = tier or cfg.get(f"models.nodes.{node}", "small")
    return p["provider"], p[tier]


def chat_model(provider: str, model: str, *, json_mode: bool = False, max_tokens: int = 700, temperature: float | None = None):
    temperature = cfg.get("models.temperature", 0.2) if temperature is None else temperature
    timeout = cfg.get("models.timeout_s", 240)
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(model=model, temperature=temperature, num_predict=max_tokens, format="json" if json_mode else None,
                          base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"), seed=7,
                          client_kwargs={"timeout": timeout}, keep_alive="30m")
    if provider == "groq":
        from langchain_groq import ChatGroq

        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        if "gpt-oss" in model:  # reasoning model: keep reasoning short and leave room for the answer
            kw["reasoning_effort"] = cfg.get("models.reasoning_effort", "low")
            max_tokens += 400
        return ChatGroq(model=model, temperature=temperature, max_tokens=max_tokens, timeout=timeout, max_retries=6,
                        model_kwargs=kw)
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        return ChatOpenAI(model=model, temperature=temperature, max_tokens=max_tokens, timeout=timeout, model_kwargs=kw)
    raise ValueError(f"unknown provider {provider}")


def price(model: str, tin: int, tout: int) -> float:
    pin, pout = (cfg.get("models.prices_usd_per_mtok", {}) or {}).get(model, [0, 0])
    return (tin * pin + tout * pout) / 1e6


_sem = asyncio.Semaphore(int(os.environ.get("LLM_CONCURRENCY", "1")))


async def chat(node: str, prompt: str | Prompt, *, json_mode: bool = False, max_tokens: int = 700,
               temperature: float | None = None, tier: str | None = None, config: dict | None = None,
               **vars: Any) -> LLMResult:
    """Render a versioned prompt and call the node's model (with cache + fallback)."""
    if os.environ.get("LLM_DISABLED") == "1":
        raise LLMUnavailable(f"{node}: LLM disabled (LLM_DISABLED=1)")
    p = load_prompt(prompt) if isinstance(prompt, str) else prompt
    system, user = p.render(**vars)
    provider, model = model_for(node, tier)
    candidates = [(provider, model)]
    fb = profile().get("fallback_small")
    if (tier or cfg.get(f"models.nodes.{node}", "small")) == "small" and fb and fb != model:
        candidates.append((provider, fb))
    use_cache = os.environ.get("LLM_CACHE", "1") == "1"
    last_err: Exception | None = None
    for prov, mdl in candidates:
        key = hashlib.sha256(json.dumps([prov, mdl, system, user, json_mode, max_tokens, temperature]).encode()).hexdigest()
        if use_cache and (hit := _cache().get(key)):
            return LLMResult(hit["text"], mdl, hit["in"], hit["out"], 0.0, True, 0.0, p.version)
        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            llm = chat_model(prov, mdl, json_mode=json_mode, max_tokens=max_tokens, temperature=temperature)
            t0 = time.perf_counter()
            async with _sem:
                msg = await asyncio.wait_for(
                    llm.ainvoke([SystemMessage(system), HumanMessage(user)],
                                config={**(config or {}), "run_name": f"llm:{node}", "metadata": {"node": node, "prompt_version": p.version}}),
                    timeout=cfg.get("models.timeout_s", 240))
            dt = time.perf_counter() - t0
            text = msg.content if isinstance(msg.content, str) else json.dumps(msg.content)
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
            um = getattr(msg, "usage_metadata", None) or {}
            tin, tout = int(um.get("input_tokens", 0)), int(um.get("output_tokens", 0))
            if use_cache:
                _cache().put(key, {"text": text, "in": tin, "out": tout})
            return LLMResult(text, mdl, tin, tout, dt, False, price(mdl, tin, tout), p.version)
        except Exception as e:  # try the fallback
            last_err = e
    raise LLMUnavailable(f"{node}: all models failed: {type(last_err).__name__}: {last_err}")


def parse_json(text: str) -> dict[str, Any]:
    """Lenient JSON extraction for small local models."""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
    return {}
