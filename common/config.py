"""Load agent/config.yaml once, with env overrides. Nothing else reads the YAML directly."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


@lru_cache(maxsize=1)
def config() -> dict[str, Any]:
    path = Path(os.environ.get("BIDPILOT_CONFIG", ROOT / "agent" / "config.yaml"))
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    if os.environ.get("MARKETPLACE_MODE"):
        cfg["marketplace"]["mode"] = os.environ["MARKETPLACE_MODE"]
    if os.environ.get("MODEL_PROFILE"):
        cfg["models"]["profile"] = os.environ["MODEL_PROFILE"]
    if os.environ.get("RAG_VARIANT"):
        cfg["rag"]["variant"] = os.environ["RAG_VARIANT"]
    if os.environ.get("POLICY_VERSION"):
        cfg["marketplace"]["policy_version"] = int(os.environ["POLICY_VERSION"])
    return cfg


def reload() -> dict[str, Any]:
    config.cache_clear()
    return config()


def get(path: str, default: Any = None) -> Any:
    cur: Any = config()
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def policy_rules() -> list[dict[str, Any]]:
    rules = list(get("policy.rules", []))
    if int(get("marketplace.policy_version", 1)) >= 2:
        rules += list(get("policy.v2_rules", []))
    return rules
