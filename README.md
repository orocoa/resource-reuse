# Resource Reuse

Look up project assets before generating, downloading or copying them again.

Resource Reuse is an agent skill and a small Python CLI for **project-local
resource libraries**. It finds exact duplicates, stores one content object per
hash, creates named read-only reference views, and materializes independent files
when a consumer needs writable or standalone copies.

**Beta, with macOS/APFS validation.** Originals stay in place. There is no automatic
deletion, cross-project material pool, background watcher or OS write interception.

## What it does

- Uses the existing [fclones](https://github.com/pkolaczk/fclones) detector for read-only duplicate scans.
- Checks project ownership, content hashes, recorded source state and reviewed purpose.
- Creates a `shared-resources` library inside each project's main folder.
- Lets multiple filenames and folders refer to one pinned, read-only content object.
- Uses independent copy-on-write files on supported macOS/APFS storage for editing and standalone exports.
- Derives exact reuse keys from ordered inputs, tool/model versions, platform and parameters.
- Generates review plans and refuses changed sources, different existing targets and cross-project access.

## Install

Install this repository as the `resource-reuse` skill using your agent's skill
installer, or place its contents in the agent's configured skills directory.
The skill entrypoint is [SKILL.md](SKILL.md) at the repository root.

The CLI can also run directly from a clone:

```sh
git clone https://github.com/orocoa/resource-reuse.git
cd resource-reuse
SKILL_DIR="$PWD"
```

Requirements:

- Python 3.9 or newer; pool operations use the standard library.
- A separately installed `fclones` executable for duplicate scans and batch plans.
- macOS/APFS for the tested COW backend. Other storage requires explicit
  `--allow-copy` where supported, which incurs ordinary copying costs.
- Symbolic-link support and a compatible consumer for reference views.

The scripts do not install dependencies automatically. See the
[fclones installation instructions](https://github.com/pkolaczk/fclones#installation).

## Quick start

Select one verified project and an existing folder of ordinary, read-only assets:

```sh
PROJECT_ROOT="/absolute/path/to/your-project"
POOL="$PROJECT_ROOT/shared-resources"
RUN_DIR="$PROJECT_ROOT/work/resource-reuse-review"
FCLONES="$(command -v fclones)"

python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" init --pool "$POOL"

python3 -B "$SKILL_DIR/scripts/library.py" --project-root "$PROJECT_ROOT" plan \
  --root "$PROJECT_ROOT/materials" --pool "$POOL" --fclones "$FCLONES" \
  --role "reviewed-local-preview" --license "same-project local use; retain original terms" \
  --out "$RUN_DIR/review-plan.json"
```

Read the private plan and check its selected paths, purpose and permitted use.
Then stage a **new** folder that references the library:

```sh
python3 -B "$SKILL_DIR/scripts/library.py" --project-root "$PROJECT_ROOT" stage \
  --plan "$RUN_DIR/review-plan.json" --to "$RUN_DIR/asset-view" --read-only-assets

python3 -B "$SKILL_DIR/scripts/views.py" --project-root "$PROJECT_ROOT" verify \
  --view "$RUN_DIR/asset-view"
```

The source directory is preserved. Repeating an identical request reuses the
existing view. For a consumer that needs independent regular files:

```sh
python3 -B "$SKILL_DIR/scripts/views.py" --project-root "$PROJECT_ROOT" export \
  --view "$RUN_DIR/asset-view" --to "$RUN_DIR/standalone-assets"
```

Keep the library and views out of source-only copies, releases and recovery
snapshots. Use a verified standalone export when those files must travel alone.
Existing non-English library directories remain supported; no migration is required.

## Reuse before producing

Use `lookup` for discovery, then `resolve` an exact ID/key. A similar filename is
only a candidate. For deterministic producers, derive the key before running the
producer, check for a verified hit, and register one result on a genuine miss.
The skill guides cooperating agents and scripts; existing producers must actually
call these entrypoints. It cannot prevent unrelated software from writing files.

See [the command reference](references/commands.md) for exact keys, runtime trees,
individual file materialization, view manifests and scan bounds.

## Validation and limits

Local validation covered real project assets, exact duplicate detection, unchanged
originals, repeated requests, writable isolation, browser image/font/video reading,
and standalone exports. Public CI runs the behavioral tests on macOS.

A bounded local comparison used 12 ordinary copies with about **14.35 MB** of file
allocation, versus **8 KiB** of metadata and zero additional asset payload in the
corresponding two reference views. This demonstrates avoided **new copy cost**;
it is not space released from the preserved originals or a promised saving for
another workload. Private datasets, paths, indexes and receipts are not published.

APFS clones may already share data blocks. Logical duplicate sizes and directory
totals are not exclusive physical allocation. New versions, screenshots and genuinely
different generated assets still consume space. Reference views depend on their
library and are not independent backups. No original-file replacement/deletion mode
is provided. Whole-application behavior, external-drive transfers, long-term net
savings and equivalent cross-platform COW behavior require separate validation.

## Run tests

Test artifacts are retained outside the repository. Choose a fresh directory for
each run:

```sh
TEST_RUN="$(python3 -c 'import tempfile; from pathlib import Path; print(Path(tempfile.mkdtemp()).resolve())')"
export RESOURCE_REUSE_TEST_ROOT="$TEST_RUN/pool-tests"
export RESOURCE_VIEW_TEST_ROOT="$TEST_RUN/view-tests"
export RESOURCE_LIBRARY_TEST_ROOT="$TEST_RUN/library-tests"
export FCLONES_BINARY="$(command -v fclones)"
python3 -B -m unittest discover -s tests -v
```

The full suite uses macOS/APFS. Detector integration tests require `fclones`; a
missing backend is reported as a skip locally and is installed explicitly in CI.

## License and provenance

[MIT](LICENSE). This composes existing work rather than introducing a new duplicate
detection algorithm. The SHA-256 helper comes from ECC; the library-first workflow
adapts cinematic-site-demo; scanning delegates to external fclones. File Organizer
was a workflow reference only, with no copied code or prose.

See [upstream decisions](references/upstream.md), [pinned sources](references/sources.json)
and [third-party notices](THIRD-PARTY-NOTICES.txt).
