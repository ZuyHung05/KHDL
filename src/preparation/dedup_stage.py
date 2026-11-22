"""Build current dedup first, then audit its own baseline (also supports a fresh workspace)."""
from . import deduplicate, audit_reconciliation
if __name__ == '__main__':
    deduplicate.run()
    audit_reconciliation.main()
