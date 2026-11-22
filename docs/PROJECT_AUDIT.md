# Project audit

Git has pre-existing uncommitted README and untracked project files. No reset or history rewrite. Complete pre-migration inventory: `project_file_inventory.json`. All protected data, raw, releases, SQLite, checkpoints and .env are retained. No deletion approved or performed. Caches retained pending verification. Collision files are archived with explicit names; no blind overwrite. CLI entrypoints include collection.runner, crawler_ingestion, classification.runner, preparation modules and scripts/profile_raw_schema.py. Preparation relies on project-root paths derived from module location. New schemas require explicit adapter/mapping; discovery is not schema understanding.

## Migration decisions and evidence

All children of IT4930 were moved to root using filesystem moves. README collision: original root saved as PRE_REFACTOR_ROOT_README_md, project README saved as LEGACY_PROJECT_README.md, new README authored. Ignore files archived before merging. Existing root docs retained; colliding children would receive IT4930_ prefix. `.env` moved intact to root and remains ignored. Nested pytest cache moved to logs/legacy_pytest_cache. No raw snapshot, manifest, Parquet, SQLite database, checkpoint, logs or intermediate was deleted. Inventory records original paths and sizes; moves preserve bytes, and existing raw/curated checksums were revalidated after migration.

Production path bug found and fixed: collection registry used ROOT.parent/docs; now uses ROOT/docs. No git reset, staging or commit performed. Existing uncommitted files preserved. Current production code paths derive root from module location. Historical docs retain old commands as archival content.

Cleanup: no files deleted. Cache inventory is available in project_file_inventory.json; no unique/intermediate artifacts were deemed safe to remove merely based on imports. A future deletion request should generate exact paths/sizes and demonstrate reproduction first. Retention must protect every snapshot referenced by released manifests and frozen corpora.

Unresolved scope: generic full new-source end-to-end integration, a corpus builder using M02 group IDs and certified label transfer are not complete. The delivered CLI coordinates existing M02 modules and provides explicit M01 execution/M03 offline checks; it is not a fully unified automatic live M01→M03 workflow.


Update: `src.classification.curated_corpus` now freezes M02-based corpora using dedup_v2 group IDs, member provenance, separate cleaned description/requirements, input hashes and release manifest. `m02_v1` was created offline: 9,427 records, 5,753 candidates; preflight PASS. Earlier statements that this builder is pending are superseded. It does not transfer legacy labels or call the API. Full new-source acquisition-to-release fixture and certified legacy label transfer remain pending.

## Follow-up priorities completed

Reconciliation now validates exact target/legacy submitted-input hashes, prediction provenance, model/prompt/taxonomy/schema versions and evidence; 104 suggestions are transferred to a separate M02 overlay, never to legacy SQLite. New-source integration now covers real registry→production ingestion (mock HTTP)→all M02 stages→curated, rerun, new version and corruption paths. CLI has locking, atomic checkpoint/resume, output validation, event logs and optional ingestion/corpus steps. Historical statements that these features are pending are superseded by TEST_REPORT.md and GITHUB_READINESS.md. Live-worker overlay import remains separate future work.

Cleanup decisions: updated .gitignore rather than deleting unique files. All data, checkpoints, releases, external ZIP archives (~1.2 GiB), migration backups and caches remain local. Current code/config/tests/docs and offline CI are publishable; no files were deleted and no commit/push performed.
