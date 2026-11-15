PY ?= .venv/Scripts/python.exe
ifeq ($(OS),)
PY = .venv/bin/python
endif
export PYTHONWARNINGS=ignore

.PHONY: install data dev api worker gigsim web test lint eval eval-rag eval-decision eval-llm smoke-eval seed seed-demo demo report graphs openapi

install:
	uv venv --python 3.12 .venv && uv pip install --python $(PY) -e ".[dev]"
	cd apps/web && npm ci

data:            ## Kaggle -> personas, GigSim seed, dev + held-out sets (seeded, deterministic)
	$(PY) -m scripts.build_data.build_all

gigsim:
	GIGSIM_INITIAL_RELEASE=all $(PY) -m uvicorn gigsim.app:app --port 18081
api:
	$(PY) -m uvicorn apps.api.main:app --port 18000 --reload
worker:
	$(PY) -m arq worker.tasks.WorkerSettings
web:
	cd apps/web && npm run dev
dev:             ## all local services (needs Postgres :15432 + Redis :16379, e.g. `docker compose up postgres redis`)
	$(MAKE) -j4 gigsim api worker web

seed seed-demo:  ## reviewer account + a few analysed jobs
	$(PY) -m scripts.seed_demo

test:
	$(PY) -m pytest -q
lint:
	$(PY) -m ruff check .
	$(PY) -m scripts.check_repo_rules

eval-rag:
	$(PY) -m evals.runners.rag_eval
eval-decision:
	LLM_DISABLED=1 $(PY) -m evals.runners.decision_eval
eval-ablation:
	$(PY) -m evals.runners.ablation
eval-llm:        ## LLM-heavy: proposals (+judge, reply rate), R&D A, R&D C, X2 A/B
	$(PY) -m evals.runners.gigsim_outcomes
	$(PY) -m evals.runners.judge_calibration
	$(PY) -m evals.runners.tool_granularity
	$(PY) -m evals.runners.arch_compare
	$(PY) -m evals.runners.ab_test
eval: eval-rag eval-decision eval-ablation   ## retrieval + decision metrics -> evals/results/*.json
	$(PY) -m scripts.build_report_tables
smoke-eval:      ## CI: 30-job smoke eval with thresholds
	LLM_DISABLED=1 $(PY) -m evals.runners.smoke

graphs:
	$(PY) -m scripts.render_graphs
openapi:
	$(PY) -c "import json; from apps.api.main import app; json.dump(app.openapi(), open('apps/api/openapi.json','w'), indent=1)"
	cd apps/web && npm run gen:api:file
report:
	$(PY) -m scripts.build_report_tables
	cd report && latexmk -pdf report.tex
demo: seed-demo dev
