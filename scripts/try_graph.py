"""Manual end-to-end run of the bid graph against GigSim (dev helper)."""
import asyncio, json, sys, time, uuid
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from agent.graphs.bid_graph import build_bid_graph
from agent.mcp_client import ToolBox
from common.tracing import run_config

async def main(job_id: str, persona: str = "ai_ml", action: str = "approve"):
    prof = json.load(open(f"data/personas/{persona}/profile.json"))
    settings = {"hourly_floor": prof["hourly_floor"], "min_fixed": prof["min_fixed"], "weekly_connects_budget": 80}
    async with ToolBox("u-demo", persona, f"dev-token-{persona}") as tb:
        g = build_bid_graph(MemorySaver(), InMemoryStore())
        tid = str(uuid.uuid4())
        cfg = run_config(f"job-{job_id}-{tid[:6]}", tid, "u-demo", toolbox=tb)
        t = time.time()
        async for ev in g.astream({"job_id": job_id, "user_id": "u-demo", "persona": persona, "settings": settings, "trace_id": tid}, cfg, stream_mode="updates"):
            for k, v in ev.items():
                if k == "__interrupt__":
                    print(f"  [{time.time()-t:6.1f}s] INTERRUPT for approval")
                else:
                    print(f"  [{time.time()-t:6.1f}s] {k}: status={v.get('status') if isinstance(v, dict) else ''} {str((v or {}).get('trace', [{}])[-1] if isinstance(v, dict) and v.get('trace') else '')[:230]}")
        st = (await g.aget_state(cfg)).values
        print("STATUS", st.get("status"), st.get("decision"), st.get("attention_reason"))
        if st.get("drafts"):
            print("DRAFT:\n", st["drafts"][-1]["cover_letter"]); print("VERIF", st.get("verification", {}).get("before"), st.get("verification", {}).get("removed"))
            print("CRITIQUES", [c["issues"] for c in st.get("critiques", [])]); print("COMPLIANCE", st.get("compliance_verdict"))
        if st.get("status") == "awaiting_approval":
            async for ev in g.astream(Command(resume={"action": action, "reason": "test"}), cfg, stream_mode="updates"):
                print("  resume:", list(ev.keys()), str(ev)[:300])
            print("FINAL", (await g.aget_state(cfg)).values.get("status"), (await g.aget_state(cfg)).values.get("submission"))

if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:]))
