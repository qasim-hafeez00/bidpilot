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


def na(x, nd: int = 3) -> str:
    """n/a when the slice has no positives (e.g. no injected jobs)."""
    return "n/a" if x is None or (isinstance(x, float) and x != x) else f(x, nd)


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
    return (r"\begin{table}[t]\centering\small" "\n" r"\caption{Retrieval quality on the full dev set (" + str(n) +
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
                    f"{f(b['scam']['precision'])} & {f(b['scam']['recall'])} & {na(b['injection_detection_recall'])} & "
                    f"{f(b['price_in_fair_band'])} & {f(b['latency_p95_s'], 2)} \\\\")
    return (r"\begin{table}[t]\centering\small\caption{Decisions on the dev set (graph in analysis-only mode through the in-memory MCP client). "
            r"n/a: the slice contains no injected jobs. Source: \texttt{decision\_eval.json}.}\label{tab:dec}" "\n"
            r"\begin{tabular}{lrrrrrrrrr}\toprule Slice & n & Bid F1 & P & R & Scam P & Scam R & Inj.\ det. & Price in band & p95 s\\\midrule"
            "\n" + "\n".join(rows) + "\n" r"\bottomrule\end{tabular}\end{table}")


def table(caption: str, label: str, cols: str, header: str, rows: list[str]) -> str:
    return (r"\begin{table}[t]\centering\small\caption{" + caption + r"}\label{" + label + "}\n"
            r"\begin{tabular}{" + cols + r"}\toprule " + header + r"\\\midrule" "\n" + "\n".join(rows) + "\n" r"\bottomrule\end{tabular}\end{table}")


def proposals() -> str:
    d = load("proposals.json")
    if not d:
        return r"\pendingtable{Proposal-level results}{evals/results/proposals.json}"
    j = (load("judge.json") or {}).get("mean_overall_by_config", {})
    rows = []
    for name, s in d["summary"].items():
        label = {"best": "Composite (shipped)", "v0": "V0 naive dense"}.get(name, name)
        rows.append(f"{esc(label)} & {s['n']} & {f(s['unsupported_per_proposal_before'], 2)} & {f(s['unsupported_per_proposal_after'], 2)} & "
                    f"{f(s['critic_loops_mean'], 2)} & {f(j.get(name), 2)} & {f(s['reply_rate'], 2)} & {f(s['p95_latency_s'], 0)} & "
                    f"{f(s['tokens_per_proposal'], 0)} & {f(s['usd_per_proposal'], 4)} \\\\")
    return table(r"Proposal-level results (" + esc(str(d.get("model_profile"))) + r" profile; " + str(d["per_persona"]) +
                 r" gold-bid jobs per persona). Unsupported claims are counted by the independent fact checker; reply rate is from "
                 r"GigSim's rule-based clients. Source: \texttt{proposals.json}, \texttt{judge.json}.", "tab:prop", "lrrrrrrrrr",
                 r"Retrieval & n & Unsup.\ before & Unsup.\ after & Critic loops & Judge (1--5) & Reply rate & p95 s & Tokens & USD", rows)


def judge_calib() -> str:
    d = load("judge.json")
    if not d:
        return r"\pendingtable{Judge calibration}{evals/results/judge.json}"
    c = d["calibration"]
    return (r"\noindent\textbf{Judge calibration.} " + esc(c["status"]) + r": quadratic-weighted $\kappa$ = " + f(c.get("kappa_quadratic"), 2) +
            r" on $n$ = " + str(c.get("n", 0)) + r" labelled proposals (" + str(len(c.get("disagreements", []))) +
            r" disagree by $\ge$2 points). Source: \texttt{judge.json}.")


def toolgran() -> str:
    d = load("tool_granularity.json")
    if not d:
        return r"\pendingtable{Tool granularity}{evals/results/tool\_granularity.json}"
    nice = {"fine": "Fine-grained (14 tools)", "coarse": "Coarse (3 tools + action)", "best": "Fine + rewritten descriptions"}
    rows = [f"{nice.get(k, k)} & {v['n']} & {f(v['tool_selection_accuracy'])} & {f(v['argument_accuracy'])} & {f(v['tokens_per_task'], 0)} & "
            f"{f(v['mean_latency_s'], 2)} \\\\" for k, v in d["results"].items()]
    return table(r"R\&D A: tool granularity with \texttt{" + esc(d["model"]) + r"}. Source: \texttt{tool\_granularity.json}.", "tab:tools",
                 "lrrrrr", r"Tool set & n & Tool sel.\ acc. & Arg.\ acc. & Tokens/task & Latency s", rows)


def arch() -> str:
    d = load("arch_compare.json")
    if not d:
        return r"\pendingtable{Architecture comparison}{evals/results/arch\_compare.json}"
    nice = {"react_single_agent": "Single ReAct agent", "langgraph_supervisor": "LangGraph supervisor", "hand_built_graph": "Hand-built graph"}
    rows = [f"{nice.get(k, k)} & {v['n']} & {f(v['bid_skip_accuracy'])} & {v['scams_bid_on']} & {f(v['unsupported_claims_per_proposal'], 2)} & "
            f"{v['compliance_violations_left']} & {f(v['tokens_per_job'], 0)} & {f(float(v['p95_latency_s']), 0)} & {v['errors']} \\\\"
            for k, v in d["summary"].items()]
    return table(r"R\&D C: the same jobs (" + str(d["per_persona"]) + r" per persona) through three architectures. Source: \texttt{arch\_compare.json}.",
                 "tab:arch", "lrrrrrrrr", r"Architecture & n & Bid/skip acc. & Scams bid & Unsup./prop. & Policy viol. & Tokens/job & p95 s & Errors", rows)


def abtest() -> str:
    d = load("ab_test.json")
    if not d:
        return r"\pendingtable{A/B test}{evals/results/ab\_test.json}"
    a, b = d["arms"]["A_problem_first"], d["arms"]["B_question_first"]
    rows = [f"A: problem-first & {a['n']} & {a['replies']} & {f(a['rate'], 2)} \\\\", f"B: question-first & {b['n']} & {b['replies']} & {f(b['rate'], 2)} \\\\"]
    return table(r"X2 A/B test on GigSim reply rate. Two-proportion $z$ = " + f(d["z"], 2) + r" ($p$ = " + f(d["p_two_prop_z"], 3) +
                 r"), Fisher exact $p$ = " + f(d["p_fisher"], 3) + r". Source: \texttt{ab\_test.json}.", "tab:ab", "lrrr",
                 r"Arm & Submitted & Replies & Reply rate", rows)


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


def _skip_group(t: str, i: int) -> int:
    """Index just after the brace group that starts at t[i] == '{'."""
    depth = 0
    for j in range(i, len(t)):
        depth += {"{": 1, "}": -1}.get(t[j], 0)
        if depth == 0:
            return j + 1
    raise ValueError("unbalanced braces")


def standalone() -> None:
    """report/main.tex = report.tex with every generated file inlined (one file compiles on Overleaf by itself)."""
    t = (ROOT / "report" / "report.tex").read_text(encoding="utf-8")
    key = "\\InputIfFileExists{generated/"
    out, i = [], 0
    while (k := t.find(key, i)) >= 0:
        out.append(t[i:k])
        name_end = t.index("}", k)
        name = t[k + len("\\InputIfFileExists{"):name_end]
        a_end = _skip_group(t, name_end + 1)          # {then}
        b_start = a_end
        b_end = _skip_group(t, b_start)               # {else}
        f = ROOT / "report" / name
        out.append(f.read_text(encoding="utf-8") if f.exists() else t[b_start + 1:b_end - 1])
        i = b_end
    out.append(t[i:])
    (ROOT / "report" / "main.tex").write_text("".join(out).replace("% Tables are generated", "% STANDALONE copy, built by scripts/build_report_tables.py. Tables are generated"), encoding="utf-8")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "rag_table.tex").write_text(rag_table(), encoding="utf-8")
    (OUT / "rag_breakdown.tex").write_text(rag_breakdown(), encoding="utf-8")
    (OUT / "ablation_table.tex").write_text(ablation(), encoding="utf-8")
    (OUT / "decision_table.tex").write_text(decision(), encoding="utf-8")
    for name, fn in (("proposals_table", proposals), ("judge_calib", judge_calib), ("toolgran_table", toolgran),
                     ("arch_table", arch), ("ab_table", abtest)):
        (OUT / f"{name}.tex").write_text(fn(), encoding="utf-8")
    (OUT / "numbers.tex").write_text(headline() + "\n", encoding="utf-8")
    standalone()
    print("wrote", sorted(p.name for p in OUT.iterdir()), "+ report/main.tex")


if __name__ == "__main__":
    main()
