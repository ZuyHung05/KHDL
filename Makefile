.PHONY: crawl-topcv crawl-description

crawl-topcv:
	python -m src.collection.crawler_ingestion --source topcv

crawl-description:
	python -m src.collection.crawler_ingestion --source $(SOURCE) --phase descriptions $(if $(filter 1 true yes,$(HEADLESS)),--headless,)

.PHONY: pipeline status test
pipeline:
	.venv/bin/python -m src.pipeline all --execute --version $(or $(VERSION),v2)
status:
	.venv/bin/python -m src.pipeline status
test:
	.venv/bin/python -m pytest -q
