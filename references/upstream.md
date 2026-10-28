# What was reused

Pinned commits, source hashes, licenses and decisions are in `sources.json`.

- **cinematic-site-demo**: adapted library-first lookup and skipping generation.
  Its fuzzy subject match is discovery; this workflow also verifies exact content,
  recipe and context. No service calls, generated media or templates are copied.
- **ECC content-hash-cache-pattern**: extracted its `compute_file_hash` Python
  example into `scripts/vendor/ecc_hash.py`, called by the pool implementation.
  The full MIT notice is retained. Recipe keys also encode ordered inputs,
  tool/version/platform and parameters.
- **fclones**: external, unmodified `group` backend. No new duplicate detector or
  bundled binary. The adapter adds metadata filtering and a read-only report.
- **File Organizer**: workflow comparison only. Its license was unconfirmed at
  the pinned root, so no code or prose is copied.
- **Existing local prototype**: generalized its content store, independent APFS
  COW materialization, origin records, verification and idempotent targets.
  Actual configurations, paths, indexes and assets were excluded. Recipe aliases
  now permit several keys to share one object.

This composes existing work; it does not claim a new duplicate-finding algorithm.

Project ownership is now mandatory: per-project pools live in their main folders, recipes include project scope, and sources/targets/scans cannot cross boundaries. There is no bundled project registry.
