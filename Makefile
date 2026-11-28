PYTHON ?= .venv/bin/python
RUN_ID ?= manual_$(shell date +%Y%m%d_%H%M%S)

.PHONY: test status crawl-monthly prepare

test:
	$(PYTHON) -m pytest -q

status:
	$(PYTHON) -m src.pipeline status

crawl-monthly:
	$(PYTHON) -m src.collection.monthly_crawl --out-dir data/monthly_crawl/$(RUN_ID)

# Optional INPUTS="data/inputs/legacy_import_20261127.parquet data/monthly_crawl/.../jobs.jsonl"
prepare:
	$(PYTHON) -m src.pipeline prepare --run-id $(RUN_ID) --execute $(foreach input,$(INPUTS),--input $(input))
