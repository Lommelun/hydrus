# Task: validate the tag graph against real multi-source data

## Goal

Everything else in this project (dedup, the query-resolution work, deciding whether the graph is worth
relying on for anything real) is more useful, or only possible, with real multi-source
(`source → PTR → personal`) tag data instead of the safebooru-scale dev sample this project has used
so far. This task is: get real data in front of the graph and confirm the existing backend holds up at
real scale.

This is a **verification task, not a one-off setup step** — treat "does it actually work at real
scale" as an open question to actually answer, not a checklist to rubber-stamp.

**The loading-mechanism question is already answered, don't redo it:** whether to replace the current
CSV-export + bulk-`COPY` approach with Ladybug's SQLite `ATTACH` extension was investigated hands-on
(2026-07-01, see `tag-graph-ladybug-engine-reference.md`'s attach section for the full, tested
findings) and the answer is **no, keep the current approach** — attach-based loading and
`UNWIND`+`CREATE` were both benchmarked directly against production-scale synthetic data and both lost
decisively to CSV+`COPY` for relationship loading (the expensive, dominant part of the work); attach
also has a confirmed silent-failure footgun in its anti-join filtering. This was a real spike with real
numbers, not speculation — no need to re-evaluate unless something about Ladybug itself changes.

**Parquet, on the other hand, is a genuinely open question specifically at real scale, worth trying
here.** Also investigated 2026-07-01 (see `tag-graph-ladybug-engine-reference.md`'s Parquet section):
at the dev-scale corpus size (71k edges) Parquet was marginally *slower* end-to-end than CSV, but at
~1.5M edges (still smaller than real-DB scale) the full pipeline (Python `pyarrow` write + Ladybug
`COPY FROM parquet`) was **1.30x faster**, and the advantage appears to grow with size. **When real
data is in and if `RebuildCoOccurrence`/`RebuildFileTags`'s CSV step is actually slow enough to notice,
try switching to `pyarrow`-written Parquet files as a direct, low-risk swap** (same `COPY` mechanism,
just a different file format) — this is a real, validated potential win, unlike the attach/`UNWIND`
question above, gated only on real numbers actually showing CSV is a bottleneck at that point.

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
   spot-checks in the visual explorer. Time it — if the CSV-write/`COPY` step is slow enough to notice
   at real scale, that's the trigger to try the Parquet swap below; if it's still fast, don't bother.
4. **If step 3 shows the CSV step is actually slow:** try swapping the CSV writer for `pyarrow`-written
   Parquet (see `tag-graph-ladybug-engine-reference.md`'s Parquet section for the validated numbers and
   exact `COPY ... FROM 'file.parquet'` syntax) and re-measure. Real, low-risk, same `COPY` mechanism —
   just don't bother if step 3 doesn't actually show a problem worth solving.

## Findings to carry into this work

See `tag-graph-hydrus-schema-reference.md` and `tag-graph-ladybug-engine-reference.md` for full detail.
On the loading mechanism (settled, see above): CSV+`COPY` is confirmed fastest for bulk relationship
loading, by a wide margin, against both alternatives actually tested. No open question left here.

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
