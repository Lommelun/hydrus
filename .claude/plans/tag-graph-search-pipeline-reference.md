# Reference: Hydrus file-search execution pipeline & autocomplete architecture

Pure facts about how Hydrus executes a file search and drives tag autocomplete today, gathered while
researching the opt-in Ladybug tag-graph backend project (see `tag-graph-index.md`). Background for
any task doc that touches search or a new query-driven feature — kept here once instead of
re-explained per doc.

## The 5-phase search pipeline

`ClientDBFilesSearch.py`'s `GetHashIdsFromQuery()` combines predicates via a **staged,
set-intersection pipeline**, not one big SQL query:

```
_Do1PreInclusiveTagPreds   (OR / hash predicates)
  -> intersection_update_qhi() into a running hash_id set
_Do2InclusiveTagPreds      (tag / namespace / wildcard searches)
  -> intersection
_Do3FileInfoPreds          (file metadata: size, mime, dimensions, etc.)
  -> intersection
_Do4InexpensivePostFileCrossReferencePreds  (ratings, service status, exclusion tags, notes)
  -> intersection
_Do5ExpensivePostFileCrossReferencePreds    (num-tags, tag-as-number, URLs, viewing stats)
  -> intersection
-> final result set
```

Tag-count predicates run **last** (phase 5) specifically because they need a `GROUP BY hash_id` over
mappings — expensive, so they only run against the set already narrowed by everything earlier. There's
no cost-based reordering beyond this fixed structure; tag predicates are simply always treated as more
expensive than file-info predicates.

**This whole pipeline runs synchronously on Hydrus's single dedicated DB thread**, inside a `Read` job.
Graph I/O has to stay off that thread (see `tag-graph-ladybug-engine-reference.md`). This means there
is **no clean way to call into the graph from inside this pipeline today** — retrofitting graph-derived
results into `_Do1`/`_Do2` would mean either blocking the DB thread on graph I/O (defeats the purpose)
or restructuring the pipeline for a mid-flight hand-off (a real, structurally nontrivial change). **This
constraint only applies if you're trying to inject the graph into the *existing* pipeline** — a brand
new, separate `Read` action for a new panel/feature isn't bound by any of this, since it can just do its
own thing on its own thread with its own result-combination logic. See `tag-graph-query-resolution.md`.

## Tag-related system predicates

Parsed in `ClientSearchParseSystemPredicates.py` into `PREDICATE_TYPE_SYSTEM_NUM_TAGS` /
`PREDICATE_TYPE_SYSTEM_TAG_AS_NUMBER`:

- `system:has tags` / `system:untagged` → `NUM_TAGS` with `('*', '>', 0)` / `('*', '=', 0)`.
- `system:number of tags [op] [n]` → `NUM_TAGS` with `('*', op, n)`.
- `system:number of tags with namespace [ns] [op] [n]` → `NUM_TAGS` with `(ns, op, n)`.
- `system:tag as number [ns] [op] [n]` → `TAG_AS_NUMBER`, a numeric parse of the *subtag itself* (e.g.
  `priority:5` matching a numeric-value predicate) — a plain string/numeric match over `subtags`
  (`GetTagAsNumSubtagIds`), **not a relationship query**. No graph benefit; leave on SQLite regardless
  of what happens with the rest.

`NUM_TAGS` executes in `_Do5ExpensivePostFileCrossReferencePreds` via
`GetHashIdsAndNonZeroTagCounts()` (~`ClientDBFilesSearch.py:2037`), which counts **display** tags
(`TAG_DISPLAY_DISPLAY_ACTUAL`) — same semantics as autocomplete's read-box counts, see
`tag-graph-hydrus-schema-reference.md`.

## Tag autocomplete architecture (why it's already fast — relevant if ever considering a graph-backed
version, even for a new surface)

GUI: `ClientGUIACDropdown.py`'s `AutoCompleteDropdownTagsWrite`/`AutoCompleteDropdownTagsRead`, both
calling `Read('autocomplete_predicates', tag_display_type, file_search_context, search_text=...)` on a
background thread (not the DB thread inline with typing — already async).

Backend: `ClientDBTagSearch.GetAutocompletePredicates()` (`ClientDBTagSearch.py:487`):
- Subtag matching, three ways depending on input: **FTS4 prefix `MATCH`** for simple prefixes (fast);
  **`LIKE`-scan fallback** for complex wildcards like `*foo*` (flagged as a scan in a code comment,
  the one genuinely weak case); **a direct searchable-subtag-map lookup** for exact matches (FTS4 exact
  lookups are noted "ultra slow" in a comment — the map was added specifically to work around that).
- Counts come from the precomputed, denormalized cache tables described in
  `tag-graph-hydrus-schema-reference.md` — not computed at query time.
- Its own result cache + request cancellation already exists client-side
  (`ClientGUIAsync.py`'s `FastThreadToGUIUpdater`) — keystrokes don't each trigger a fresh full query.

**Net assessment (informed this project's decision to drop graph-backed autocomplete as a
*replacement*):** the common path (simple prefix, any exact match) is already about as fast as it can
be without a fundamentally different index; the only weak spot is the complex-wildcard `LIKE` scan,
a narrow case. A graph traversal doesn't obviously beat FTS4 prefix matching + a cache-table count
lookup. A *new*, separate graph-backed input widget for a *new* surface (per
`tag-graph-query-resolution.md`) is a different question — that's about resolving ambiguous/related
tags via graph relationships, not about beating SQLite's raw string-matching speed.

## Related docs

- `tag-graph-hydrus-schema-reference.md` — the underlying tables/caches this pipeline reads.
- `tag-graph-query-resolution.md` — the task that needs to work around the DB-thread constraint above.
