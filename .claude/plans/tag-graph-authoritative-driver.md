# Task: making the graph an authoritative, live driver (long-term, undecided)

## Status: not started, not decided, explicitly gated

This is long-term architectural work. **Do not start this without the other tasks
(`tag-graph-real-data-validation.md`, `tag-graph-query-resolution.md`,
`tag-graph-suggestions-and-dedup.md`) showing the graph is worth relying on for something specific
first.** The project's end-state — full SQLite-tag-layer retirement vs. a permanent hybrid where the
graph is authoritative for select relationships only — is deliberately undecided; this doc describes
what "authoritative" would actually require if/when that's revisited, not a commitment to build it.

## Goal (per the user's stated ideal for this track)

Once the graph *is* the authoritative driver for a given relationship (e.g. file→tag mappings,
sibling/ancestry), it should be kept live — updated on every relevant SQLite write (new file/tag
added, PTR sync, any maintenance task) — not just periodically rebuilt. And critically: **existing
components (search, tag listing for files/results, autocomplete) should not be replaced** — the right
shape is a driver-swap/decoupling pattern where the same read/write action can be satisfied by either
backend, confirmed explicitly by the user, not a rip-and-replace of working code.

## What's already live-synced vs. not (current state)

`hydrus/client/graph/ClientGraphSync.py` subscribes to the `content_updates_gui` pubsub (published
post-commit from `ClientDB.py`'s `_DoAfterJobWork()`) and handles:
- `CONTENT_TYPE_TAG_SIBLINGS` ✓
- `CONTENT_TYPE_TAG_PARENTS` ✓
- `CONTENT_TYPE_MAPPINGS` — **not handled at all.** File-tag mappings are 100% rebuild-only today
  (`ClientGraphProjections.RebuildFileTags`/`RebuildCoOccurrence`, triggered manually or on a
  schedule) — there is currently no live path for mapping writes to reach the graph.

## The PTR write-path finding (matters for this task specifically)

Confirmed by reading `ClientDB.py`: normal tag writes go
`Write('content_updates', package)` → `ClientDB.py` dispatch → `ClientDBContentUpdates.
ProcessContentUpdatePackage()` → per-type handlers → post-commit pubsub publish (what
`ClientGraphSync` listens to). **PTR repository sync does not go through this path at all** —
`_ProcessRepositoryContent` (`ClientDB.py`, dispatched via `'process_repository_content'`) calls the
same underlying DB modules (`modules_content_updates.UpdateMappings`,
`modules_tag_parents.AddTagParents`, `modules_tag_siblings.AddTagSiblings`, etc.) **directly, in
autothrottled bulk chunks**, bypassing `ProcessContentUpdatePackage` and its pubsub publish entirely.

**Practical implication:** even sibling/parent live-sync (which does exist today) never actually sees
PTR-sourced changes incrementally — only a full rebuild (`ClientGraphMigrate.ImportFromHydrusDB`)
picks those up, because it reads SQLite's own already-resolved caches directly rather than relying on
the pubsub feed. This isn't a correctness bug (rebuilds are correct), it's a *freshness* gap between
rebuilds — and it means "make PTR live-sync work" is really "make *any* live-sync work for a
bulk-bypass write path," a materially different and harder problem than the sibling/parent case.

## Why naive incremental sync doesn't work at PTR scale

Already measured (see `tag-graph-ladybug-engine-reference.md`): per-edge Cypher `MERGE` is ~230x
slower than bulk `COPY` (607s vs 2.65s for 71k edges in the dev-scale corpus). PTR-scale sibling/parent
and mapping data is orders of magnitude larger than that. A naive "call `MergeEdge` once per incoming
PTR row" incremental-sync design would not keep up. Any real live-sync design for PTR-scale data needs
either batching+periodic bulk-flush (blurring the line between "live" and "frequent rebuild"), or a
fundamentally different write mechanism this project hasn't explored yet.

## What "driver-swap/decoupling" would actually require

Not designed yet — flagging the shape of the problem, not a solution:
- Existing `Read`/`Write` actions that currently only touch SQLite (search, autocomplete, tag listing)
  would need a seam where a graph-backed implementation *could* satisfy the same action, selected by
  option or context, without changing every call site.
- `tag-graph-search-pipeline-reference.md` documents why the *search* pipeline specifically can't have
  the graph spliced in mid-flight today (DB-thread constraint, no clean hand-off point) — a real seam
  there is a separate, structurally nontrivial piece of work, not a side effect of anything else in
  this project.
- Whatever shape this takes, it needs to preserve the existing components working exactly as they do
  now when the graph-backed path isn't engaged — no regression risk to the default experience.

## SQLite `ATTACH` extension doesn't solve this

Worth ruling out explicitly since it's easy to conflate with this task: Ladybug's SQLite `ATTACH`
extension (see `tag-graph-ladybug-engine-reference.md`) lets Cypher read a SQLite table directly, which
could simplify *rebuild* mechanics (see `tag-graph-real-data-validation.md`) — but it's a
triggered scan/import, not a live view, and doesn't provide a mechanism for the graph to be notified
of new SQLite writes as they happen. It's orthogonal to this task, not a shortcut for it.

## Related docs

- `tag-graph-index.md` — overview and links.
- `tag-graph-search-pipeline-reference.md` — why the search pipeline specifically resists a live seam.
- `tag-graph-ladybug-engine-reference.md` — the perf numbers and `ATTACH` extension limits behind the
  reasoning above.
- `tag-graph-real-data-validation.md`, `tag-graph-query-resolution.md`,
  `tag-graph-suggestions-and-dedup.md` — the work that should come first and inform whether this is
  worth pursuing at all.
