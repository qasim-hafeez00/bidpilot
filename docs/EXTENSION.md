# Signature extension: X2 proposal experiments

Two proposal strategies run as an A/B test in GigSim:

* **A: problem-first.** Open with the client's problem, then evidence with numbers.
* **B: question-first.** Open with one clarifying question, then evidence.

Jobs are assigned alternately to A or B (stratified by persona). Each strategy is a style instruction appended to the
Writer prompt, so everything else is held constant. Reply rates are compared with a two-proportion z-test and Fisher's
exact test (`evals/runners/ab_test.py`, results in `evals/results/ab_test.json`).

Opening style is recorded on every submitted proposal (`pipeline.opening_style`). Outcome memory then promotes an
insight only when both arms have n ≥ 5 and the reply rates differ by ≥ 15 points, so a real winner reaches the Writer
through the same promotion rule rather than a hand edit.

Status: the runner and wiring are implemented. The measurement needs about 2 × 30 local LLM proposal drafts and is pending
on the CPU-only machine.
