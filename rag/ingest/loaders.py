"""Loaders: PDF CV, Markdown case studies, repo READMEs + code, reviews, past proposals (with outcome).

Every document gets metadata: persona, type, project_id, evidence_id, title, skills, date, client_industry, outcome.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from common.skills import extract_skills

PERSONA_ROOT = Path(__file__).resolve().parents[2] / "data" / "personas"
CODE_EXT = {".py", ".ts", ".js", ".sql", ".R", ".gs", ".bas", ".graphql", ".yml", ".yaml", ".json", ""}


@dataclass
class Doc:
    doc_id: str
    text: str
    meta: dict[str, Any] = field(default_factory=dict)


def _front_matter(raw: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", raw, re.S)
    if not m:
        return {}, raw
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def load_cv(persona: str, root: Path = PERSONA_ROOT) -> list[Doc]:
    pdf = root / persona / "cv" / "cv.pdf"
    text = ""
    if pdf.exists():
        from pypdf import PdfReader

        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages)
    if not text.strip() and (root / persona / "cv" / "cv.md").exists():
        text = (root / persona / "cv" / "cv.md").read_text(encoding="utf-8")
    if not text.strip():
        return []
    return [Doc(f"{persona}:cv", text, {"persona": persona, "type": "cv", "project_id": None, "evidence_id": f"{persona}:cv",
                                        "title": "CV", "skills": extract_skills(text), "date": None, "source": str(pdf.name)})]


def load_case_studies(persona: str, root: Path = PERSONA_ROOT) -> list[Doc]:
    out = []
    for f in sorted((root / persona / "case_studies").glob("*.md")):
        fm, body = _front_matter(f.read_text(encoding="utf-8"))
        title = re.search(r"^# (.+)$", body, re.M)
        out.append(Doc(fm.get("id", f"{persona}:{f.stem}"), body.strip(), {
            "persona": persona, "type": "case_study", "project_id": fm.get("id", f"{persona}:{f.stem}"),
            "evidence_id": f"{persona}:case:{f.stem}", "title": title.group(1) if title else f.stem,
            "skills": fm.get("skills") or extract_skills(body), "date": str(fm.get("date", "")),
            "client_industry": fm.get("client_industry"), "source": f"case_studies/{f.name}"}))
    return out


def load_repos(persona: str, root: Path = PERSONA_ROOT) -> list[Doc]:
    out = []
    for repo in sorted(p for p in (root / persona / "repos").glob("*") if p.is_dir()):
        pid = f"{persona}:{repo.name}"
        readme = repo / "README.md"
        if readme.exists():
            t = readme.read_text(encoding="utf-8")
            out.append(Doc(f"{pid}:readme", t, {"persona": persona, "type": "readme", "project_id": pid,
                                                "evidence_id": f"{persona}:repo:{repo.name}", "title": f"{repo.name} README",
                                                "skills": extract_skills(t), "source": f"repos/{repo.name}/README.md"}))
        for f in sorted(repo.rglob("*")):
            if f.is_file() and f.name != "README.md" and (f.suffix in CODE_EXT or f.name == "Dockerfile"):
                t = f.read_text(encoding="utf-8", errors="ignore")
                rel = f.relative_to(repo).as_posix()
                out.append(Doc(f"{pid}:code:{rel}", f"# file: {repo.name}/{rel}\n{t}", {
                    "persona": persona, "type": "code", "project_id": pid, "evidence_id": f"{persona}:repo:{repo.name}",
                    "title": f"{repo.name}/{rel}", "skills": extract_skills(t + " " + f.name), "source": f"repos/{repo.name}/{rel}"}))
    return out


def load_reviews(persona: str, root: Path = PERSONA_ROOT) -> list[Doc]:
    p = root / persona / "reviews.json"
    if not p.exists():
        return []
    return [Doc(r["review_id"], r["text"], {"persona": persona, "type": "review", "project_id": r["project_id"],
                                            "evidence_id": r["review_id"], "title": f"Client review ({r['rating']}/5)",
                                            "skills": extract_skills(r["text"]), "date": r["date"],
                                            "client_industry": r.get("client_industry"), "source": "reviews.json"})
            for r in json.loads(p.read_text(encoding="utf-8"))]


def load_proposals(persona: str, root: Path = PERSONA_ROOT) -> list[Doc]:
    p = root / persona / "proposals.json"
    if not p.exists():
        return []
    return [Doc(r["proposal_id"], f"Job: {r['job_title']}\n{r['text']}", {
        "persona": persona, "type": "proposal", "project_id": r.get("cited_project_id"), "evidence_id": r["proposal_id"],
        "title": f"Past proposal: {r['job_title'][:60]}", "skills": extract_skills(r["job_title"] + " " + r["text"]),
        "date": r["date"], "outcome": r["outcome"], "style": r.get("style"), "source": "proposals.json"})
            for r in json.loads(p.read_text(encoding="utf-8"))]


def load_persona(persona: str, root: Path = PERSONA_ROOT) -> list[Doc]:
    return (load_cv(persona, root) + load_case_studies(persona, root) + load_repos(persona, root)
            + load_reviews(persona, root) + load_proposals(persona, root))


def load_uploads(owner: str, upload_dir: Path) -> list[Doc]:
    """User-uploaded portfolio (own-profile mode): .md/.txt case studies, .pdf CV, proposals.json."""
    docs: list[Doc] = []
    for f in sorted(upload_dir.glob("*")):
        if f.suffix == ".pdf":
            from pypdf import PdfReader

            t = "\n".join((pg.extract_text() or "") for pg in PdfReader(str(f)).pages)
            typ = "cv"
        elif f.suffix in (".md", ".txt"):
            t = f.read_text(encoding="utf-8", errors="ignore")
            typ = "case_study"
        else:
            continue
        pid = f"{owner}:{f.stem}"
        docs.append(Doc(pid, t, {"persona": owner, "type": typ, "project_id": pid if typ == "case_study" else None,
                                 "evidence_id": f"{owner}:upload:{f.stem}", "title": f.stem, "skills": extract_skills(t),
                                 "source": f"upload/{f.name}"}))
    return docs
