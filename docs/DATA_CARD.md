# Data card

Builder: `scripts/build_data/build_all.py` (seed 4016, deterministic). Every record has a `provenance` field.

## Sources

| Dataset (Kaggle) | Used for | Real/synthetic | Notes |
|---|---|---|---|
| ahmedmyalo/upwork-freelance-jobs-60k | Job text, Upwork skill tags, client stats (payment verified, spend, rating, reviews, hires, country), Connects cost, applicants | **Real** | 63,950 rows; 27,713 usable after filtering (description length 250–3,500 chars, a budget present, at least one mapped skill). |
| asaniczka/upwork-job-postings-dataset-2024-50k-records | Market pricing percentiles per domain (hourly midpoints, fixed budgets) | **Real** | 53,058 rows; values outside $2–$50k dropped. |
| adityammantri/trial-1 | Scam phrasing appended to ~30% of synthetic scam posts; external scam text | Real (labelled fraudulent postings; the text itself looks templated) | `fraudulent == 1` rows only. |
| sarveshchhetri/freelancer-success-earnings-and-churn-prediction | **Examined, rejected** | — | Hourly rates are capped (median $280 for every skill), so they are useless for calibrating rates. |
| asaniczka/freelance-contracts-dataset-1-3-million-entries | **Not used** | — | Redundant with the postings for pricing; too large for this machine. |
| asaniczka/all-jobs-on-upwork-200k-plus | Downloaded, not used in the final build | — | Titles only (no descriptions). |

Licences: check each Kaggle page. The derived real-data files committed here (`data/gigsim_seed/`, `evals/datasets/`)
contain job text and aggregate client statistics only, with emails and URLs removed at build time.

## Synthetic data (clearly labelled)

* **Personas** (`data/personas/{ai_ml,fullstack,data_analyst}`): fictional names marked "(synthetic persona)". Each has a
  CV (PDF + Markdown), 17–18 case studies, 11–12 repositories (README + code), reviews and 150 past proposals labelled
  won/replied/ignored. Proposal job titles are real; the bodies are synthetic.
* **Hard-for-RAG properties:** implied skills appear only in code imports and as paraphrases in prose. Each project is
  described three ways (case study, README, proposal). Code and prose are mixed.
* **Outcome model for past proposals:** P(reply) = base by style (specific 0.34, question 0.30, generic 0.07) + 0.18 × relevance;
  P(won | reply) = 0.45 (0.2 for generic proposals).
* **Clients:** real aggregate statistics plus synthetic hidden preferences (must-have skills, budget ceiling, dislike of
  generic openings, preference for short proposals, responsiveness) and a short synthetic history.
* **Scams** (10% of each split): a real in-domain job with a synthetic payload (off-platform contact, unpaid work,
  upfront fee, off-platform payment, credentials, too-good-to-be-true). Scam clients are mostly unverified with $0 spend.
* **Injections** (7.5%): one of four planted instructions inserted mid-description in a real job.
* **Low-budget variants** (~17%): a real in-domain job with the budget lowered.
* **Screening questions:** sampled per domain from a small bank.

## Splits and gold labels

* `evals/datasets/dev_<persona>.jsonl`: 200 jobs per persona (45% in-domain, 15% adjacent, 15% off-domain, 10% scam,
  7.5% injection, the rest low-budget).
* Held-out split: 80 jobs per persona with new clients, written to `data/processed/` (**git-ignored**). It stands in for the
  instructor's hidden set.
* **Gold:** `bid` iff not a scam, all *core* skills (skills named in the title) are in the persona's skills, coverage ≥ 0.5,
  and the price is feasible (client's max rate ≥ the persona's hourly floor, or budget ≥ minimum fixed price).
  Gold evidence is the projects whose explicit and implied skills overlap the job's skills, graded by overlap (ubiquitous skills
  weigh 0.25 at evaluation time). The fair price band is the client's posted range blended with market p40–p75 (hourly), or
  ±15% of the posted budget (fixed).

## Limitations

* The same author wrote the persona generator and the system: vocabulary overlap makes retrieval easier than on a stranger's portfolio.
* Gold bid/skip comes from skill coverage, not human judgement.
* The Upwork postings are from 2024; prices may be outdated.
* Client behaviour in GigSim is a model, not real clients. Reply rates measure fit to that model only.

## Handling

* `.env`, raw Kaggle files, the held-out split, GigSim databases and audit logs are git-ignored.
* PII (emails, phones, cards, IBANs, tokens) is masked at intake and in every log.
