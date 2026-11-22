.PHONY: crawl-itviec crawl-linkedin crawl-topcv crawl-topdev crawl-vietnamworks crawl-description

crawl-itviec:
	python -m src.collection.crawler_ingestion --source itviec -- --pages 60

crawl-topdev:
	python -m src.collection.crawler_ingestion --source topdev -- --pages 300

crawl-vietnamworks:
	python -m src.collection.crawler_ingestion --source vietnamworks -- --pages 60

crawl-topcv:
	python -m src.collection.crawler_ingestion --source topcv

crawl-linkedin:
	python -m src.collection.crawler_ingestion --source linkedin

# Run separately after the listing crawler for SOURCE has finished.
crawl-description:
	python -m src.collection.crawler_ingestion --source $(SOURCE) --phase descriptions $(if $(filter 1 true yes,$(HEADLESS)),--headless,)

.PHONY: pipeline status test
pipeline:
	.venv/bin/python -m src.pipeline all --execute --version $(or $(VERSION),v2)
status:
	.venv/bin/python -m src.pipeline status
test:
	.venv/bin/python -m pytest -q
