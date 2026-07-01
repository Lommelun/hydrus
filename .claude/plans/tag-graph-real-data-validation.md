# Task: validate the tag graph against real multi-source data

## Goal

Everything else in this project (dedup, the query-resolution work, deciding whether the graph is worth
relying on for anything real) is more useful, or only possible, with real multi-source
(`source → PTR → personal`) tag data instead of the safebooru-scale dev sample this project has used
so far. This task is: get real data in front of the graph, confirm the existing backend holds up at
real scale, and — as part of that — evaluate whether the current CSV-export + bulk-`COPY` loading
approach should be replaced by Ladybug's SQLite `ATTACH` extension.

This is a **verification and evaluation task, not a one-off setup step** — treat "does it actually
work at real scale" and "is there a better loading mechanism" as open questions to actually answer,
not a checklist to rubber-stamp.

## What's already built (don't redo)

- `hydrus/client/graph/ClientGraphMigrate.py`'s `ImportFromHydrusDB` — one-time full importer for the
  relationship layer (siblings/parents/ideals), reads SQLite's own already-resolved caches.
- `hydrus/client/graph/ClientGraphProjections.py`'s `RebuildCoOccurrence` and `RebuildFileTags` — bulk
  CSV-export + `COPY`-based rebuilders for co-occurrence and the storage-level file/tag mirror.
- Both already validated against synthetic/dev-scale data (a deterministic fixture + a real ~3000-post
  safebooru corpus). See `tag-graph-index.md` for exact commit references.

## Procedure

**Work against a copy, never the live database, until this backend has proven itself:**

1. Copy the real Hydrus `db/` (or wherever the live install's data lives) to a scratch location.
2. Boot a client against the copy with `enable_tag_graph` on, let `ImportFromHydrusDB` run, and confirm
   real, recognizable relationships show up in the tag graph explorer
   (`hydrus/client/gui/ClientGUIGraphExplorer.py`). This is additive-only by design (reads SQLite via
   normal `Read(...)` actions, writes only into a new `<db_dir>/graph/` subdirectory — nothing touches
   the SQLite files), but this hasn't been exercised at real multi-million-tag scale yet. Watch for:
   import time, disk usage, memory, and anything that looks structurally wrong (missing relationships,
   wrong ideals, crashes).
3. Run `RebuildCoOccurrence` and `RebuildFileTags` against the real data; sanity-check output against
   spot-checks in the visual explorer.
4. **Evaluate the SQLite `ATTACH` extension as a replacement for the current CSV-export step.** See
   `tag-graph-ladybug-engine-reference.md` for exact syntax
   (`ATTACH 'db' AS x (dbtype sqlite)`, then `LOAD FROM x.table` or `COPY NativeTable FROM x.table`).
   Concretely try rewriting one of the existing rebuilders (`RebuildFileTags` is the simpler one — it's
   a near-direct mirror of `current_mappings_{service_id}`) to load via `ATTACH`+`COPY` instead of
   Python `sqlite3` + a temp CSV file, and compare:
   - Code simplicity (does it actually remove the CSV-writing dance, or just relocate it?).
   - Performance at real scale, against the already-measured baseline (~230x speedup of bulk `COPY`
     over per-row `MERGE`, from the dev-scale corpus — does `ATTACH`-based loading beat, match, or lose
     to the current CSV approach at real scale?).
   - Whether the co-occurrence computation (currently Python `itertools.combinations` + lift-weighting
     over data pulled into memory) could be pushed into SQL via the attached table instead, or whether
     that's not worth the complexity.
   - **This is read-only from SQLite's side and additive to the graph** — safe to try directly, no
     special caution needed beyond the standing "work against the copy" rule.

## Findings to carry into this work

See `tag-graph-hydrus-schema-reference.md` and `tag-graph-ladybug-engine-reference.md` for full detail.
Headline points:
- The `ATTACH` extension is real, but it's a *scan/import* operation you trigger, not a live view —
  it doesn't make the graph automatically stay current as SQLite changes underneath it. It may
  simplify/speed up **how** a rebuild reads data; it does not solve the separate live-sync question
  (that's `tag-graph-authoritative-driver.md`'s territory).
- Its docs don't show a single query joining an attached SQLite table with native graph structures —
  don't assume you can write one Cypher query that reads live SQLite *and* traverses the graph at once.

## Once real data is in

Use it to:
- Revisit dedup with real cross-source data — see `tag-graph-suggestions-and-dedup.md`.
- Inform whether `tag-graph-query-resolution.md`'s first deliverable (a search-input widget) or
  anything else is actually worth building next.
- Decide, later and separately, whether to ever point the *live* daily-driver client at this feature —
  not part of this task.

## Related docs

- `tag-graph-index.md` — overview and links.
- `tag-graph-hydrus-schema-reference.md`, `tag-graph-ladybug-engine-reference.md` — background facts.
- `tag-graph-suggestions-and-dedup.md`, `tag-graph-query-resolution.md` — what real data unblocks.
