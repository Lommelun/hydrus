# Task: suggestions & dedup via Ladybug's graph algorithms

## Goal

Upgrade tag suggestions and (separately) tag dedup/synonym detection to use Ladybug's own graph
algorithms — the `algo` extension (Louvain, PageRank) now, the `vector` extension (embeddings) later —
instead of hand-rolled Python. Per the user: keep things simple until this is actually worth building,
but this is the intended direction, not a maybe.

## What's already built (don't redo)

- `ClientGraphProjections.RebuildCoOccurrence` — pruned, lift-weighted tag co-occurrence, computed in
  Python (`itertools.combinations` + a lift formula) and bulk-CSV-loaded into `CO_OCCURS` edges.
- `ClientGraphSuggestions.GetRelatedTags` — reads that projection, excluding the tag itself, its ideal,
  ancestors, and existing siblings. Verified against a deterministic fixture's hand-designed ranking.
- Both already graph-only (don't read SQLite for suggestions at query time) — see `tag-graph-index.md`.

## Dedup: what was already tried and why it failed

String-similarity + same-namespace heuristics were tested against real safebooru/danbooru data and
found unworkable:
- Can't distinguish true synonyms from unrelated similar tags — `black_shirt`/`black_skirt` and
  `1girl`/`1girls` are both edit-distance-1, same (empty) namespace, indistinguishable on any lexical
  axis tried.
- No ground truth to test against from single-source data — safebooru/danbooru already normalize
  aliases away before tagging, so the "bad" side of a real synonym essentially never appears in the
  corpus.
- The one plausible real signal — cross-source co-occurrence of the same concept tagged differently by
  different importers (e.g. `kitty_ears` from one source, `cat_ears` from another, on the same file) —
  needs real multi-source data to even attempt. See `tag-graph-real-data-validation.md`.

## Where Ladybug's `algo` extension fits (see `tag-graph-ladybug-engine-reference.md` for exact syntax)

- **Louvain community detection** — the standout candidate. Run over a projected graph of
  `CO_OCCURS` (and possibly `SIBLING_OF`) edges, it clusters related tags directly, which is a much
  more principled dedup/synonym-candidate signal than string similarity: two tags that consistently
  co-occur with the same neighborhood, or that are already siblings across services, should land in
  the same community. Real multi-source data (see `tag-graph-real-data-validation.md`) is what would
  let this be evaluated for real — same blocker as the abandoned heuristic, different, better tool.
- **PageRank** — could rank tag importance within a neighborhood, useful for tuning suggestion
  ordering or for sizing/highlighting nodes in the visual explorer
  (`hydrus/client/gui/ClientGUIGraphExplorer.py` / `ClientGraphVisualize.py`).
- Both run via `PROJECT_GRAPH(...)` then a procedure call, scanned from disk on demand — no need to
  materialize a separate copy of the graph for this.

## Where the `vector` extension fits (explicitly future, not needed now)

Embedding-based similarity (HNSW index, `CREATE_VECTOR_INDEX`/`QUERY_VECTOR_INDEX`) — for tag
embeddings (semantic similarity beyond graph structure) or file embeddings (visual/content similarity),
possibly paired with an LLM-based recommendation layer per the user's own framing. Needs an actual
embedding source (an image or text embedding model) that hasn't been chosen. No documented
incremental-update story in Ladybug's docs for this index type — likely a rebuild-on-add situation,
not confirmed. Don't start this until the simpler `algo`-based approach has been tried and its limits
are actually understood.

## Suggested first steps (not fully designed yet)

1. Once real multi-source data is available (`tag-graph-real-data-validation.md`), try `PROJECT_GRAPH`
   + Louvain over the real `CO_OCCURS`/`SIBLING_OF` graph and manually inspect a sample of the
   resulting communities — do they look like plausible synonym/duplicate-candidate groups?
2. If promising, design a review UI for surfacing candidate clusters to the user (accepted pairs still
   go through the normal `Write('content_updates', ...)` sibling-write path, per the original project's
   locked decision — no direct graph writes bypassing Hydrus's own content-update system).
3. PageRank-based suggestion re-ranking is a smaller, independent experiment — could be tried earlier,
   even on dev-scale data, since it doesn't need real cross-source data to be meaningful.
4. Vector/embeddings: revisit only after 1-3 above, and only if still wanted.

## Related docs

- `tag-graph-index.md` — overview and links.
- `tag-graph-ladybug-engine-reference.md` — exact `algo`/`vector` extension syntax.
- `tag-graph-real-data-validation.md` — the blocker for meaningfully evaluating any of this.
