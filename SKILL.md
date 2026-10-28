---
name: resource-reuse
description: Find duplicates and reuse assets within one verified project through a content-addressed library, named read-only reference views or independent COW copies. Use before generating/copying assets and when organizing project resources. Preserves originals; no cross-project sharing or automatic cleanup.
---

# Resource Reuse: Look Up Before Creating

Use an existing suitable resource from the same project before producing another copy. Match content,
version, platform, inputs, parameters, purpose and permitted use. A similar name
or subject is a search candidate, never proof that resources are equivalent.

## Use the existing workflow

- Read existing resource manifests or pool configuration first. Preserve maintained
  project paths, package-manager stores and the user's chosen tools/models.
- Resolve the project from the current thread/project association and its actual main folder. Do not equate matching names, hashes or topics with project ownership.
- Put the pool inside that project’s verified main folder, normally `PROJECT_ROOT/shared-resources`. Never create a desktop-wide or cross-project material pool. Keep it ignored by Git and excluded from source copies, releases and recovery packages.
- Use `--project-root` when context is ambiguous. Registries may hold project boundary metadata, but lookups select only one project. Nested products remain separate, including products grouped in one workspace.
- Each pool binds its project identity. Adding another project’s source, resolving its pool, scanning mixed-project roots or writing a result into another project is refused. Equal bytes do not override these boundaries.
- Unassigned and retired recovery caches are not active reuse inputs. Leave originals in place until their ownership is verified.
- Use `scripts/reuse.py` for pool operations (Python 3.9+, standard library).
  Read [commands.md](references/commands.md) for commands and producer integration.
- For duplicate reviews use `scripts/scan.py`, which delegates to **fclones group**.
  Use a separately installed fclones binary. A missing backend is not permission
  to download tools or implement a replacement scanner.
- For an existing asset folder, `scripts/library.py plan` generates a bounded, private review manifest from the real detector and the existing pool. After reviewing purpose/use, `stage` rechecks all source hashes/states and creates a new reference view without hand-writing resource IDs. See [commands.md](references/commands.md#batch-plan-and-stage). Prefer selected material folders over rebuilding a whole-machine index.

## Reuse before creating

1. Select the verified main folder, then `lookup` only in its pool by name/version or an existing exact key. Check origin and purpose.
   Private materials and historical evidence retain their original intended use.
2. For deterministic producers derive `key` from ordered input content hashes,
   tool/model version, platform and parameters. Prompt text alone cannot prove
   identical generated image bytes. Respect requests for fresh variations.
3. `resolve` verifies the selected existing file/tree and returns its path for
   read-only use. Preserve the consuming software's filename/type/path contract.
4. For a new directory of reviewed read-only assets, use `scripts/views.py` to create a **reference view**: original filenames/directories map to pinned objects in this project's library. Several names or views use the same object without copying payload bytes. Read [commands.md](references/commands.md#reference-views) for its manifest and commands.
   Use views only where the consumer supports links and treats assets as read-only. Keep views in ignored project work/cache directories. `views.py export` makes verified independent regular files for a consumer/export that cannot follow the library; it never overwrites a different destination. Never substitute a view for source code, application databases, managed dependencies or independently editable fixtures.
5. For writable isolation or a project-local file that cannot be a link use `materialize`. It refuses
   a different existing target. On macOS/APFS it creates independent COW files,
   not writable hard links. `materialize-tree` reuses an identical existing tree;
   keep genuinely independent test states in separate COW trees.
6. Only on a genuine miss complete the already authorized producer once, then
   `add` its result with the exact key and purpose. The scripts do not execute
   producers, download assets or change external services themselves.

## Review without altering originals

Do not ask again for roots or preservation rules already supplied. The scan
adapter sends only eligible paths to fclones, excluding cloud placeholders,
links, managed packages and common secrets. Write local private reports to a new
path outside scanned inputs and the shareable skill.

Independent per-project files may still benefit from transparent filesystem COW block sharing; they never share a writable inode or a cross-project lookup. Duplicate bytes are a logical upper bound. APFS clones may already share blocks.
Separate observed volume changes, metadata costs and future copies avoided;
a dry run must never be described as having freed disk space.

No command deletes/replaces an original, bulk moves files, uploads data, adds a
watcher, or invokes fclones remove/link/dedupe. Do not bypass this boundary with
other shell commands. A later destructive-cleanup request needs its own concrete,
reviewable recovery plan.

For existing duplicates, scanning and registering them is preparation, not reclamation. Show the selected paths, same-project canonical object, intended read-only view/COW strategy and compatibility/recovery checks before replacing any old copies. A new view leaves the old copies in place and frees none of their space. Existing APFS-shared copies may already have little additional data cost. Do not repeatedly build an inventory/cache and count its logical contents as savings.

Test a real consumer before adoption: read/decode representative linked assets, then verify the self-contained export has no links and still works. Preserve source hashes and metadata before/after. Purpose markers containing `needs-review`, `unreviewed` or `unassigned` are not permission to reuse; an explicitly reviewed new purpose may get a new metadata record while the historical record is preserved.

## Report

State what was found/reused, which originals remain, skipped/changed inputs,
whether the producer actually ran, and the measured space change. This workflow
guides cooperating agents and producers; it does not intercept every application's
writes or force existing scripts to query a pool.

## Provenance and sharing

The workflow adapts cinematic-site's MIT library-first pattern; hashing reuses
ECC's MIT Python helper; scanning uses external unmodified fclones. The pool derives
from an existing tested local prototype. See [upstream.md](references/upstream.md)
and `THIRD-PARTY-NOTICES.txt`.

Distribute code, instructions, licenses and fictional examples only. Keep real
pools, inventories, user paths, reports, credentials, assets and downloaded binaries
outside the shareable folder.
