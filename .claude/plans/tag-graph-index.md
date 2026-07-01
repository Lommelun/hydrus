# Tag graph project: index

An opt-in graph-database (Ladybug, a maintained Kùzu fork) layer alongside Hydrus's SQLite tag
storage — `enable_tag_graph` option, default off, zero overhead when off, new
`hydrus/client/graph/` package, decoupled enough that upstream Hydrus pulls still merge cleanly.

This is the entry point for this project. It replaces a single monolithic plan file that had grown
into an unusable append-only history log — see below for what's done, then open whichever task
document below matches what you're working on next. Each task document is meant to be readable
standalone, with no other context needed.

## What's done and verified (don't redo)

- **Foundation** — schema (`Tag`/`TagService`/`File` nodes, `SIBLING_OF`/`IDEAL_OF`/`PARENT_OF`/
  `CO_OCCURS`/`TAGGED` rels), a one-time full importer (`ClientGraphMigrate.ImportFromHydrusDB`) that
  mirrors SQLite's own already-resolved sibling/ancestor caches correctly under cross-service
  `source → PTR → personal` precedence, and a forward-only live sync for sibling/parent writes
  (`ClientGraphSync.py` — mapping writes are not live-synced, see
  `tag-graph-authoritative-driver.md`). Commits `ad54a029`, `7a2897b9`.
- **Suggestions** — pruned, lift-weighted tag co-occurrence (`ClientGraphProjections.
  RebuildCoOccurrence`), bulk-CSV-loaded (~230x faster than per-edge writes); related-tag lookup
  (`ClientGraphSuggestions.GetRelatedTags`) reads only from the graph. Commits `0d12273f`,
  `870e568b`, sibling-exclusion bugfix `239a168f`.
- **Visual explorer** — `hydrus/client/gui/ClientGUIGraphExplorer.py` (in-app list browser:
  siblings/ancestors/related) plus `hydrus/client/graph/ClientGraphVisualize.py` (a D3
  force-directed node-link diagram opened in the browser, click-to-reveal exploration, no
  QtWebEngine dependency). JS execution verified via `jsdom`, not just string-matched HTML. Commits
  `401196d3`, `fcefbaad`.
- **File/tag mirror** — `ClientGraphProjections.RebuildFileTags`, a storage-level (not
  sibling/parent-collapsed) `File`+`TAGGED` mirror, validated against real data, kept off every
  production path — pure validation, nothing depends on it yet. Commit `a786cbfe`.

Verify all of this still passes with `just test-only client_graph` (`QT_QPA_PLATFORM=offscreen`)
before building on top of it.

## Explicitly dropped (not deferred)

- **Tag autocomplete as a replacement for the existing SQLite one** — already fast, already
  precomputed/off-thread, moving it risks regressing the app's hottest path for a narrow win. A
  *new*, separate graph-backed input widget for a new surface is a different question — see
  `tag-graph-query-resolution.md`.

## Task documents — pick whichever matches what you're doing next

1. **`tag-graph-real-data-validation.md`** — **start here if nothing else is obviously next.**
   Verify the backend against real multi-source data (via a copy of the real `db/`), and evaluate
   replacing the CSV-export loading approach with Ladybug's SQLite `ATTACH` extension. Unblocks
   everything below.
2. **`tag-graph-query-resolution.md`** — the shared capability of resolving a raw/free-text tag query
   into tags or files via the graph. First deliverable: a new, standalone search-input widget.
   Downstream uses (a new search panel, gallery-downloader query resolution, subscription filters)
   are applications of this, not separate features.
3. **`tag-graph-suggestions-and-dedup.md`** — replace hand-rolled co-occurrence/string-similarity
   with Ladybug's `algo` extension (Louvain/PageRank), and eventually `vector` (embeddings).
4. **`tag-graph-authoritative-driver.md`** — long-term, undecided, explicitly gated on 1-3 above:
   making the graph a live, authoritative driver for specific relationships via a driver-decoupling
   pattern, never a replacement of existing components.

## Shared-knowledge reference documents (facts, not tasks — linked from the docs above)

- **`tag-graph-hydrus-schema-reference.md`** — Hydrus's SQLite tag schema, the storage-vs-display
  distinction, `GetImplies`, display-mapping caches.
- **`tag-graph-search-pipeline-reference.md`** — the 5-phase file-search pipeline, system predicates,
  the existing autocomplete architecture.
- **`tag-graph-ladybug-engine-reference.md`** — Ladybug/Kùzu engine facts, bulk-load perf, the
  `attach`/`vector`/`algo` extensions, the `bugscope` visualization tool evaluation.

## Open, undecided question

Whether this project's end-state is a full "SQLite tag layer retired" flip, or a permanent hybrid
where the graph is authoritative for specific use cases (suggestions/exploration arguably already
qualify) while SQLite stays authoritative for storage/search indefinitely. Deliberately not decided —
revisit once the task documents above produce real results, not before.
