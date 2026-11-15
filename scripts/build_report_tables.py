"""Generate report/generated/*.tex from evals/results/*.json so every number in the report traces to a results file.
Missing measurements render as \\pending{} instead of being typed by hand.

    python -m scripts.build_report_tables
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "evals" / "results"
OUT = ROOT / "report" / "generated"
NICE = {"v0": "V0 naive dense", "v1": "V1 decomposition", "v2": "V2 hybrid BM25+dense", "v3": "V3 + cross-encoder",
        "v4": "V4 outcome-aware", "v5": "V5 multi-vector", "v6": "V6 contextual", "v8": "V8 corrective (CRAG)",
        "best": "Composite (shipped)"}


def load(name: str) -> dict | None:
    p = RES / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def f(x, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and x != x):
        return r"\pending{}"
    return f"{x:.{nd}f}" if isinstance(x, float) else str(x)


def esc(s: str) -> str:
    return s.replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def rag_table() -> str:
    d = load("rag_variants.json")
    if not d:
        return r"\pendingtable{RAG variant comparison}{evals/results/rag\_variants.json}"
    rows = []
    v0 = next((v for v in d["variants"] if v["variant"] == "v0"), None)
    for v in d["variants"]:
        o = v["overall"]
        delta = (o["recall@5"] - v0["overall"]["recall@5"]) * 100 if v0 else None
        rows.append(f"{NICE.get(v['variant'], v['variant'])} & {f(o['recall@5'])} & {f(o['mrr'])} & {f(o['ndcg@10'])} & "
                    f"{'+' if delta and delta > 0 else ''}{f(delta, 1) if delta is not None else '--'} & {f(o['p95_latency_s'], 2)} \\\\")
    n = d["variants"][0]["overall"]["n"]
    return (r"\begin{table}[t]\centering\small" "\n" r"\caption{Retrieval quality of every variant on the dev set (" + str(n) +
            r" non-scam jobs with gold evidence, 3 personas). Source: \texttt{evals/results/rag\_variants.json}.}\label{tab:rag}" "\n"
            r"\begin{tabular}{lrrrrr}\toprule Variant & R@5 & MRR & nDCG@10 & $\Delta$R@5 (pts) & p95 s\\\midrule" "\n" +
            "\n".join(rows) + "\n" r"\bottomrule\end{tabular}\end{table}")


def rag_breakdown() -> str:
    d = load("rag_variants.json")
    if not d:
        return ""
    keep = [v for v in d["variants"] if v["variant"] in ("v0", "v2", "v3", "best")]
    groups = ["ai_ml", "fullstack", "data_analyst"]
    jt = sorted({k for v in keep for k in v["by_job_type"]})
    lines = []
    for g in groups:
        lines.append(esc(g) + " & " + " & ".join(f(v["by_persona"].get(g, {}).get("recall@5")) for v in keep) + r" \\")
    lines.append(r"\midrule")
    for g in jt:
        lines.append(esc(g) + " & " + " & ".join(f(v["by_job_type"].get(g, {}).get("recall@5")) for v in keep) + r" \\")
    return (r"\begin{table}[t]\centering\small\caption{Recall@5 by persona and job type. Source: \texttt{rag\_variants.json}.}\label{tab:ragbreak}"
            "\n" r"\begin{tabular}{l" + "r" * len(keep) + r"}\toprule Slice & " + " & ".join(NICE[v["variant"]] for v in keep) +
            r"\\\midrule" "\n" + "\n".join(lines) + "\n" r"\bottomrule\end{tabular}\end{table}")


def ablation() -> str:
    d = load("ablation.json")
    if not d:
        return r"\pendingtable{Ablation of the composite pipeline}{evals/results/ablation.json}"
    rows = [f"{esc(r['config'])} & {f(r['recall@5'])} & {f(r['ndcg@10'])} & {f(r.get('delta_recall5_pts'), 1)} \\\\" for r in d["rows"]]
    return (r"\begin{table}[t]\centering\small\caption{Ablation: one component removed at a time. Source: \texttt{ablation.json}.}\label{tab:abl}"
            "\n" r"\begin{tabular}{lrrr}\toprule Configuration & R@5 & nDCG@10 & $\Delta$R@5\\\midrule" "\n" + "\n".join(rows) +
            "\n" r"\bottomrule\end{tabular}\end{table}")


def decision() -> str:
    d = load("decision_eval.json")
    if not d:
        return r"\pendingtable{Decision quality}{evals/results/decision\_eval.json}"
    rows = []
    for name, b in [("All", d["overall"])] + [(k, v) for k, v in d["by_persona"].items()]:
        rows.append(f"{esc(name)} & {b['n']} & {f(b['bid_skip']['f1'])} & {f(b['bid_skip']['precision'])} & {f(b['bid_skip']['recall'])} & "
                    f"{f(b['scam']['precision'])} & {f(b['scam']['recall'])} & {f(b['injection_detection_recall'])} & "
                    f"{f(b['price_in_fair_band'])} & {f(b['latency_p95_s'], 2)} \\\\")
    return (r"\begin{table}[t]\centering\small\caption{Decisions on the dev set (graph in analysis-only mode through the in-memory MCP client). "
            r"Source: \texttt{decision\_eval.json}.}\label{tab:dec}" "\n"
            r"\begin{tabular}{lrrrrrrrrr}\toprule Slice & n & Bid F1 & P & R & Scam P & Scam R & Inj.\ det. & Price in band & p95 s\\\midrule"
            "\n" + "\n".join(rows) + "\n" r"\bottomrule\end{tabular}\end{table}")


def headline() -> str:
    """\\newcommand macros for numbers quoted in prose."""
    m = {}
    d = load("rag_variants.json")
    if d:
        by = {v["variant"]: v["overall"] for v in d["variants"]}
        for k, v in by.items():
            m[f"rag{k}Rfive"] = f(v["recall@5"])
            m[f"rag{k}Ndcg"] = f(v["ndcg@10"])
    e = load("decision_eval.json")
    if e:
        o = e["overall"]
        m.update(decF=f(o["bid_skip"]["f1"]), decScamP=f(o["scam"]["precision"]), decScamR=f(o["scam"]["recall"]),
                 decInj=f(o["injection_detection_recall"]), decPrice=f(o["price_in_fair_band"]), decPninetyfive=f(o["latency_p95_s"], 2))
    return "\n".join(rf"\newcommand{{\{k.replace('0', 'zero').replace('1', 'one').replace('2', 'two').replace('3', 'three').replace('4', 'four').replace('5', 'five').replace('6', 'six').replace('8', 'eight')}}}{{{v}}}" for k, v in m.items())


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rag_table.tex").write_text(rag_table(), encoding="utf-8")
    (OUT / "rag_breakdown.tex").write_text(rag_breakdown(), encoding="utf-8")
    (OUT / "ablation_table.tex").write_text(ablation(), encoding="utf-8")
    (OUT / "decision_table.tex").write_text(decision(), encoding="utf-8")
    (OUT / "numbers.tex").write_text(headline() + "\n", encoding="utf-8")
    print("wrote", sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
