"""Render both graphs from code to Mermaid (docs/images/*.mmd). Paste into mermaid.live or GitHub to view."""
from __future__ import annotations

from pathlib import Path

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph

OUT = Path(__file__).resolve().parents[1] / "docs" / "images"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, g in (("bid_graph", build_bid_graph()), ("conversation_graph", build_conversation_graph())):
        mm = g.get_graph().draw_mermaid()
        (OUT / f"{name}.mmd").write_text(mm, encoding="utf-8")
        (OUT / f"{name}.md").write_text(f"# {name}\n\nRendered from code by `make graphs`.\n\n```mermaid\n{mm}\n```\n", encoding="utf-8")
        print("wrote", name)


if __name__ == "__main__":
    main()
