# Task: graph-backed tag query resolution (a shared capability, not a single feature)

## Goal

Build a reusable capability: given a raw or free-text tag query, resolve it — via the graph
(siblings, parents, co-occurrence, eventually fuzzy/vector matching) — into either a canonical tag set
or a `hash_id` set of matching files. This is deliberately framed as **one underlying capability with
several possible downstream consumers**, not several separate features. Per explicit user direction:
think about what's a distinct feature vs. an outcome of a shared approach — the consumers below are
applications of this capability once it exists, not separate initiatives to plan independently.

**First concrete deliverable:** a new, standalone graph-backed search-input widget — something that
takes a user's typed tag/phrase and resolves it to real tag matches via the graph. New and separate
from the existing SQLite autocomplete, not a replacement for it (see
`tag-graph-search-pipeline-reference.md` for why replacing the existing one isn't worth it).

## Why this shape (not a search bridge, not a gallery-dl feature, as the starting point)

Two ideas that came up look like separate features but are really the same underlying mechanism
pointed at different consumers:

- **A new experimental file-search panel.** Once the resolution capability exists, intersecting its
  resolved `hash_id` set with SQLite's non-tag system predicates (size, mime, dimensions, ratings,
  etc.) is comparatively easy — **because a new panel gets its own `Read` action, not bound by the
  existing 5-phase search pipeline's DB-thread constraint** (see `tag-graph-search-pipeline-reference.md`
  for exactly why that constraint exists and why it only bites when retrofitting the *old* pipeline).
  This is where "search bridge" naturally lives — as a follow-up of building this panel, not a
  separate track with its own dispatch-seam problem to solve.
- **Gallery-downloader / importer query resolution.** The user's concrete example: a query like
  "multiple girls" could resolve to `multiple_girls`, `girls`, or `group`+`girls` together, depending
  on the actual sibling/parent/co-occurrence relationships in the graph — useful for resolving a
  human's search intent into the actual tag(s) an importer should download against.
- **Subscription / importer tag whitelist-blacklist filters.** Same resolution capability, used to
  decide whether an incoming file's tags match a filter expressed in more human/flexible terms than
  Hydrus's current exact-tag-based filters.

All three want the same core thing: turn an ambiguous or free-text tag expression into a concrete,
correct set of tags or files. Build that once, well, then decide which consumer to wire up first —
likely the search-input widget or the search panel, since those are the most directly testable/useful
on their own.

## Findings that shape the design

See `tag-graph-hydrus-schema-reference.md` for full detail. Load-bearing points:

- **Storage vs. display semantics.** The existing `RebuildFileTags` mirror
  (`ClientGraphProjections.py`) is storage-level — raw `current_mappings_{service_id}`. But any
  correct resolution needs **display** semantics: sibling-collapsed *and* parent-implied
  (`ClientDBTagDisplay.GetImplies` — tagging a file `cat` should also match a query for `animal` if
  `cat`→`animal` is a parent chain). SQLite itself doesn't compute this live; it reads a separately
  maintained cache table (`cache_current_display_mappings_*`,
  `ClientDBFilesSearch.GetHashIdsFromTag`). **A new display-level graph projection is a real
  prerequisite here** — not something to defer as a "storage vs display" decision later.
- **`PARENT_OF`'s existing direction is wrong for this.** The current schema's `PARENT_OF` means
  "is an ancestor of" (child→ancestor, already flattened — see
  `tag-graph-ladybug-engine-reference.md`'s notes on how the importer built this). Resolving "what
  files match this ideal, including files tagged with its descendants" needs the *reverse* direction —
  a new query, distinct from `ClientGraphSuggestions`'s existing ancestor-walking usage.
- **Co-occurrence weighting already exists** (`ClientGraphProjections.RebuildCoOccurrence`,
  `ClientGraphSuggestions.GetRelatedTags`) and could inform "fuzzy" resolution (e.g. suggesting
  `group`+`girls` for "multiple girls" if those consistently co-occur) — a reasonable first-pass
  signal before reaching for the `vector`/`algo` extensions covered in
  `tag-graph-suggestions-and-dedup.md`.

## Suggested first steps (not fully designed yet)

1. Build the display-level projection (mirrors `cache_current_display_mappings_cache_*` per
   `tag-graph-hydrus-schema-reference.md`, same bulk-CSV or `ATTACH`-based pattern as
   `tag-graph-real-data-validation.md` settles on).
2. Build a resolution function: raw query string → candidate tag(s), using ideal resolution + siblings
   + (optionally) co-occurrence-based fuzzy suggestions.
3. Wire it into a minimal new search-input widget to actually use and evaluate it interactively — the
   fastest way to tell if the resolution logic is any good is to type real queries into it.
4. Only after that's working: consider the file-search-panel and gallery-downloader/subscription
   consumers, in whichever order turns out to matter more once real data (see
   `tag-graph-real-data-validation.md`) is available to test against.

## Related docs

- `tag-graph-index.md` — overview and links.
- `tag-graph-hydrus-schema-reference.md`, `tag-graph-search-pipeline-reference.md` — background facts.
- `tag-graph-real-data-validation.md` — needed for meaningful testing.
- `tag-graph-suggestions-and-dedup.md` — a more principled fuzzy-matching signal, once built.
- `tag-graph-authoritative-driver.md` — only relevant if this capability later needs to become
  *authoritative* rather than an additional, separate surface.
