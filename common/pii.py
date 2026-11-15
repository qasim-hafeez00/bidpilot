"""PII masking for logs, traces and the audit log (R9 / E4)."""
from __future__ import annotations

import logging
import re
from typing import Any

PATTERNS = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("PHONE", re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")),
    ("TOKEN", re.compile(r"\b(?:gsk|sk|lsv2|gho|ghp|xox[bp])[-_][A-Za-z0-9_\-]{10,}\b")),
    ("BEARER", re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{12,}")),
]


def mask(text: str) -> str:
    if not text:
        return text
    for label, pat in PATTERNS:
        text = pat.sub(f"[{label}]", text)
    return text


def mask_obj(obj: Any, _depth: int = 0) -> Any:
    if _depth > 8:
        return obj
    if isinstance(obj, str):
        return mask(obj)
    if isinstance(obj, dict):
        return {k: ("[REDACTED]" if k.lower() in {"authorization", "access_token", "refresh_token", "api_key", "password", "token"}
                    else mask_obj(v, _depth + 1)) for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return type(obj)(mask_obj(v, _depth + 1) for v in obj)
    return obj


class PiiFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = mask(str(record.msg))
        if record.args:
            record.args = tuple(mask_obj(a) for a in (record.args if isinstance(record.args, tuple) else (record.args,)))
        return True


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if any(isinstance(f, PiiFilter) for h in root.handlers for f in h.filters):
        return
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s trace=%(trace_id)s %(message)s", defaults={"trace_id": "-"}))
    h.addFilter(PiiFilter())
    root.addHandler(h)
    root.setLevel(level)
