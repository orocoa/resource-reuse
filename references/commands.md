# Commands and producer integration

Use `SKILL_DIR` for the skill. Verify `PROJECT_ROOT` from the user’s thread and main project folder; set `POOL="$PROJECT_ROOT/shared-resources"`. Keep `RUN_DIR` inside the same project, outside the pool and scanned inputs.
Actual resources, configuration and reports belong outside the skill. There is
no preloaded inventory or hardcoded user path.

## Files

```sh
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" init --pool "$POOL"
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" lookup --pool "$POOL" --query "font or version"
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" key --input "$INPUT" --tool "example-renderer" --version "1.0" --platform "example-platform" --params-json '{"width":640}'
```

With the returned key, check for a verified hit:

```sh
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" resolve --pool "$POOL" --key "$KEY"
```

A miss returns a nonzero result. The agent may then run the producer already
authorized by the user. Register the result once:

```sh
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" add --pool "$POOL" --source "$RESULT" --key "$KEY" --kind image --role "project-asset" --license "reviewed-for-this-use"
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" materialize --pool "$POOL" --id "$ID" --to "$TARGET"
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" verify --pool "$POOL"
```

`resolve` returns an existing read-only object path whose internal name is a hash.
When an importer needs the original suffix or a project-relative URL, materialize
to a correctly named target instead of changing the application's path contract.
An identical target is reused. Multiple recipe keys may share one content object.

## Configuration and runtime trees

Optional `--config` precedes the subcommand. A private external registry may contain a `projects` array of `{id, root, pools, trees}` records; only the selected project is searched. A single-project config may use `project_root`, `project_id`, `pools` and `trees`. Never put several different projects into one flat pools list. `config.example.json` is empty; no personal registry or tree is bundled.

`clone-tree --source SOURCE --to NEW` returns a verified tree SHA-256. To reuse a
cached tree, add a record to caller-owned external configuration:

```json
{
  "project_root": "PROJECT_MAIN_FOLDER",
  "project_id": "example-project",
  "pools": [],
  "trees": [{
    "name": "example-runtime-v1",
    "path": "EXTERNAL_CACHE_PATH",
    "sha256": "VERIFIED_TREE_SHA256",
    "reuse_key": "runtime:tool-version-platform-inputs"
  }]
}
```

```sh
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" --config "$CONFIG" lookup --query "example-runtime-v1"
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" --config "$CONFIG" resolve --key "$TREE_KEY"
python3 -B "$SKILL_DIR/scripts/reuse.py" --project-root "$PROJECT_ROOT" --config "$CONFIG" materialize-tree --key "$TREE_KEY" --to "$FIXED_ISOLATED_TARGET"
```

An identical existing destination is kept unchanged; a different one is retained
with an error. Use `clone-tree` for intentionally fresh independent test states.
Store source archive identity, licenses and producer recipe beside external tree
records. A matching version string alone is insufficient for pinned builds.

## Duplicate review

```sh
python3 -B "$SKILL_DIR/scripts/scan.py" --project-root "$PROJECT_ROOT" --root "$MATERIALS" --fclones "$FCLONES" --out "$RUN_DIR/duplicates.json"
```

Only scan roots within the selected project; using several projects in one call is refused. The adapter runs only `fclones group --stdin --depth 0 --hash-fn sha256` on a
metadata-filtered list. No hash-cache, transforms, link following or mutation
modes are enabled. Newline/non-UTF-8 paths are explicitly skipped because this
fclones stdin interface is line-delimited. Reports include exclusions and changes.

## Reference views

To let new folders read the library without copying the content, register selected
same-project resources with a reviewed purpose, then provide a private manifest:

```json
{"entries": [
  {"path": "images/cover.png", "id": "SELECTED_RESOURCE_ID"},
  {"path": "another-section/cover.png", "id": "SELECTED_RESOURCE_ID"}
]}
```

```sh
python3 -B "$SKILL_DIR/scripts/views.py" --project-root "$PROJECT_ROOT" create --pool "$POOL" --manifest "$RUN_DIR/view-spec.json" --to "$RUN_DIR/asset-view" --read-only-assets
python3 -B "$SKILL_DIR/scripts/views.py" --project-root "$PROJECT_ROOT" verify --view "$RUN_DIR/asset-view"
python3 -B "$SKILL_DIR/scripts/views.py" --project-root "$PROJECT_ROOT" resolve --view "$RUN_DIR/asset-view" --path "images/cover.png"
```

Both names point to one read-only content object through relative symbolic links.
The private `.resource-view.json` records the selected project, resource IDs,
content hashes and sizes. The resolver checks that every link still points to its
pinned object. A repeated identical request keeps the view unchanged; different
existing paths are never overwritten. No new asset payload is stored in the view.
Missing/corrupt objects, changed links, unreviewed purposes, foreign pools/targets
and unexpected files cause an error with the existing contents retained.

The read-only flag records an explicit consumer choice, not a security boundary:
the file owner can change permissions. Use `materialize` for editable copies.
Views require symlink support and a consumer that follows links. A web server,
bundler, archiver or external drive can have a different path/link contract; verify
that contract before integrating a real project. Keep a view and its pool together;
never present a view alone as a standalone release or independent backup.

For existing duplicates: **scan → review purpose → add one canonical object →
create/verify a new view → test the consumer → separately authorize old-copy
replacement**. Until the last step, originals remain and no old space is released.
Do not derive physical savings from the sum of reference sizes.

To give a consumer independent files without any library links:

```sh
python3 -B "$SKILL_DIR/scripts/views.py" --project-root "$PROJECT_ROOT" export --view "$RUN_DIR/asset-view" --to "$RUN_DIR/self-contained-assets"
```

Export pins every file hash, refuses unrelated existing targets and verifies
independent regular files. On supported macOS/APFS it uses COW. On other storage,
`--allow-copy` explicitly permits ordinary copies and their full storage cost.
The command stays within the project; it is not an external-drive transfer check.

## Batch plan and stage

```sh
python3 -B "$SKILL_DIR/scripts/library.py" --project-root "$PROJECT_ROOT" plan --root "$PROJECT_ROOT/materials" --pool "$POOL" --role "reviewed-local-preview" --license "same-project local use; retain original terms" --fclones "$FCLONES" --out "$RUN_DIR/review-plan.json"
python3 -B "$SKILL_DIR/scripts/library.py" --project-root "$PROJECT_ROOT" stage --plan "$RUN_DIR/review-plan.json" --to "$RUN_DIR/asset-view" --read-only-assets
```

The plan selects known asset types, uses the original fclones detector, and
records original paths, signatures, hashes, matching library IDs, exclusions,
purpose and permitted use. It does not import files or change originals.
Read it before staging. Default bounds are 1,000 assets and 512 MiB; narrow the
roots or explicitly raise `--max-files`/`--max-bytes` for larger authorized work.
Plans, views and reports belong outside scanned inputs and inside this project.

Stage validates the plan fingerprint and every original's current content/state
before registering any objects or creating the view. It reuses reviewed pool
matches; otherwise it registers one object per unique content and type. Existing
unreviewed historical metadata is preserved when a new purpose is explicitly
reviewed. A second identical request leaves the view in place. There is no old
file replacement/deletion mode. This bridges scan → library → named view, not
whole-machine cleanup or interception of every application's writes.

## Limits

Scanning requires external fclones. Pool operations use Python's standard library.
COW is implemented and tested on macOS/APFS. Other platforms/filesystems stop by
default; `--allow-copy` explicitly permits ordinary copying and its storage cost.
They have not received equivalent COW validation.

This is a single-user cache, not a privileged service or independent backup.
Application databases, credentials and recovery archives retain native management.
Sharing a cached file does not grant permission to publish its content.

## Existing global or legacy pools

Do not silently migrate old pools or attach a different project’s pool. Confirm the main folders, partition source ownership and preserve recovery evidence first. This project-bound schema intentionally refuses unowned/legacy pools rather than falling back to a global lookup. Unknown ownership remains inactive.
