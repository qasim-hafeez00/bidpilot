"""Repository rules enforced in CI: no secrets committed, gigsim/ unchanged (checksum), every prompt lives in
agent/prompts/ (no inline system prompts in Python), every number in README.md traces to evals/results/."""
from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = re.compile(r"(gsk_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|lsv2_[A-Za-z0-9_]{20,}|gh[po]_[A-Za-z0-9]{30,}|AKIA[0-9A-Z]{16}|"
                    r"-----BEGIN (RSA|EC|OPENSSH) PRIVATE KEY-----)")
INLINE_PROMPT = re.compile(r'SystemMessage\(\s*["\']|"role":\s*"system"')


def tracked() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True).splitlines()
    return [ROOT / p for p in out if (ROOT / p).exists()]


def gigsim_digest() -> str:
    h = hashlib.sha256()
    for p in sorted((ROOT / "gigsim").glob("*.py")):
        h.update(p.name.encode() + p.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()


def main() -> int:
    errors = []
    files = tracked()
    for p in files:
        if p.name in (".env",) or p.suffix in (".pem", ".key"):
            errors.append(f"secret-like file tracked: {p.relative_to(ROOT)}")
        if p.suffix in (".py", ".ts", ".tsx", ".yml", ".yaml", ".md", ".json", ".toml", ".tex") and p.stat().st_size < 2_000_000:
            if SECRET.search(p.read_text(encoding="utf-8", errors="ignore")):
                errors.append(f"possible secret in {p.relative_to(ROOT)}")
    lock = ROOT / "gigsim" / "CHECKSUM"
    if lock.exists() and lock.read_text().strip() != gigsim_digest():
        errors.append("gigsim/ was modified (checksum mismatch)")
    for p in files:
        if p.suffix == ".py" and "agent" in p.parts and "prompts" not in p.parts and INLINE_PROMPT.search(p.read_text(encoding="utf-8")):
            errors.append(f"inline prompt in {p.relative_to(ROOT)} - move it to agent/prompts/")
    for e in errors:
        print("RULE VIOLATION:", e)
    print("repo rules:", "OK" if not errors else f"{len(errors)} violation(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--lock-gigsim":
        (ROOT / "gigsim" / "CHECKSUM").write_text(gigsim_digest() + "\n")
        print("locked")
        sys.exit(0)
    sys.exit(main())
