# Reference: Ladybug/Kùzu engine facts, extensions, and visualization options

Pure facts about Ladybug (the maintained Kùzu fork this project uses) gathered while building the
opt-in tag-graph backend (see `tag-graph-index.md`). No task framing — background for any task doc.

## Bulk loading: `COPY ... FROM "csv"` vs per-row `MERGE`

**Use `COPY` for anything beyond a few hundred edges.** Measured on the real ~3000-post safebooru
corpus: 71,356 `CO_OCCURS` edges took 607.79s with per-row Cypher `MERGE`/`execute()`, vs 2.65s with a
CSV + `COPY` — about **230x**. Sibling/parent loading in `ClientGraphMigrate.py` stays on per-row
`MERGE` because that data is small (dozens to low hundreds of edges per real DB); anything
projection-scale (co-occurrence, file/tag mappings) must use bulk `COPY`. This measurement is why
`tag-graph-authoritative-driver.md`'s live-incremental-sync question rules out naive per-write graph
updates at PTR scale.

**`COPY` fails the whole batch on ANY duplicate primary key** — not an upsert. Before bulk-loading
`Tag` nodes, diff the incoming set against `MATCH (t:Tag) RETURN t.tag` and only `COPY` new ones. A
single duplicate row aborts the entire `COPY`, including unrelated new rows in the same file.

**`COPY` needs `PARALLEL=FALSE` if a value might contain a quoted newline** — the default parallel CSV
reader throws on a value like `"tag\nwith\nnewline"`. Commas/quotes/apostrophes are fine; only embedded
newlines need the flag. Hydrus strips control characters from tags before saving, so this is
defensive, not a known-hit case, but cheap enough to always set.

**`COPY` works fine across mixed-type primary keys** — confirmed for `TAGGED(File→Tag)`: `File`'s PK
is `hash_id INT64`, `Tag`'s PK is `tag STRING`. A CSV with columns `hash_id, tag, service_key` bound
positionally on the first try.

## Concurrency & connections

**`ladybug.Database(path, read_only=True)` works concurrently alongside a live writer connection** —
confirmed reading a graph file with a real live write-holding connection open elsewhere, via a
separate read-only connection, no error, real data back. A second *writable* connection to the same
path does fail with a clear lock error naming the holding PID.

## Cypher quirks

**Undirected pattern matching (`-[r:REL]-` with no arrow) works on a directed rel table in both
directions.** This is why `CO_OCCURS` (semantically undirected) is stored once per pair under a
canonical ordering rather than as two directed edges — querying from either tag's side still finds it.

**Parameterized Cypher (`$param`) works for property values, including inside `LIMIT`** —
`MATCH (t:Tag) RETURN t.tag LIMIT $limit` with `{'limit': 2}` works, not just in `WHERE`/property maps.

## Interop with Hydrus's SQLite

**Hydrus's DB thread batches commits — doesn't commit to disk after every `Write()`.** A direct
external `sqlite3.connect()` can see stale/empty data immediately after a write, even though Hydrus's
own in-process connection already reflects it. Call `db.ForceACommit()` (on `ClientDB.DB`/`HydrusDB`,
routes through `Write('null', True)`) before any direct-SQLite read that needs freshness. Rarely
matters in production (idle-maintenance rebuilds naturally run well after the normal commit cycle) —
mainly a test-fixture, write-then-immediately-read timing hazard.

**`hydrus_db` is NOT a consistent object across contexts** — in tests it's the raw `ClientDB.DB`
instance; in production it's the real `ClientController`. They expose different attributes
(`ClientDB.DB` has `.ForceACommit()` directly; `ClientController` only via `.db.ForceACommit()`;
neither reliably has the same `.db_dir`-equivalent). Functions needing filesystem access take an
explicit `db_dir: str` parameter rather than deriving it from `hydrus_db`.

## Extension: SQLite attach (`docs.ladybugdb.com/extensions/attach/sqlite/`)

Confirmed real, read-oriented:

```
ATTACH 'university.db' AS uw (dbtype sqlite);
LOAD FROM uw.person RETURN *;          -- scan the attached table
COPY Person FROM uw.person;            -- import into a native Ladybug table, no CSV needed
```

- Ladybug caches the attached table's schema (names/types) to avoid re-fetching it every query.
- **No write-back to SQLite** — read-only from Ladybug's side.
- **No confirmed single-query join between an attached SQLite table and native Ladybug graph
  structures** in the docs reviewed — examples show separate operations (scan via `LOAD FROM`, then
  separately `MATCH` against the graph), not a combined query. So this simplifies *how* a rebuild
  reads SQLite data (no Python `sqlite3` connection, no intermediate CSV file for the `COPY` step) —
  it does not provide a live view that auto-updates as SQLite changes, and it doesn't let a single
  Cypher query traverse both stores at once. See `tag-graph-real-data-validation.md` (evaluate
  replacing the current CSV approach with this) and `tag-graph-authoritative-driver.md` (why this
  alone doesn't solve live sync).

## Extension: vector (`docs.ladybugdb.com/extensions/vector/`)

HNSW index (two hierarchical layers — a full lower layer, a sampled upper layer):

```
CALL CREATE_VECTOR_INDEX(
    <TABLE_NAME>, <INDEX_NAME>, <PROPERTY_NAME>,
    mu := 30, ml := 60, pu := 0.05, metric := 'cosine', efc := 200, cache_embeddings := true);

CALL QUERY_VECTOR_INDEX(<TABLE_NAME>, <INDEX_NAME>, <QUERY_VECTOR>, <K>, efs := 200)
RETURN node.id, distance;
```

- Vector property must be an `ARRAY` of `FLOAT`/`DOUBLE`, **node tables only** currently.
- Tunables: `mu`/`ml` (max degree per layer), `efc` (construction candidates), `efs` (search
  candidates) — higher = more accurate, more compute.
- **No documented incremental-update story** — likely rebuild-on-add at this maturity, not confirmed
  either way.
- Needs an actual embedding source (image/text model) to be useful — not chosen, not urgent. See
  `tag-graph-suggestions-and-dedup.md`.

## Extension: algo (`docs.ladybugdb.com/extensions/algo/`)

Runs graph algorithms as Cypher procedures over a **projected graph** (a filtered subset of
nodes/rels), scanned from disk on demand, not materialized in memory:

```
CALL PROJECT_GRAPH('Graph', ['Person'], ['KNOWS']);
-- then run an algorithm against the projection
```

Five algorithms available: **K-Core Decomposition**, **Louvain** (community detection), **PageRank**,
**Strongly Connected Components**, **Weakly Connected Components**.

- **Louvain** is the standout for tag-clustering-based dedup/synonym-candidate detection — groups
  related tags into communities directly, a more principled signal than string similarity.
- **PageRank** could rank tag importance for suggestions or visualization node sizing.
- See `tag-graph-suggestions-and-dedup.md` for how these apply to this project.

## Visualization option: `bugscope` (github.com/LadybugDB/bugscope)

LadybugDB's own visualization tool, evaluated as an alternative to this project's existing custom
D3-in-browser explorer (`hydrus/client/graph/ClientGraphVisualize.py`):

- Real, force-directed graph viz: drag/zoom/pan, hover labels, dark/light mode, optional LLM-powered
  cluster naming via an API token.
- **Built with Tauri** — needs a Rust/Cargo toolchain to build/run (`cargo tauri dev
  --features=icebug-analytics -- -- ../test.lbdb`), and requires **a separately-running "ladybugdb
  backend API" server on `localhost:3001`** to function — not just pointing it at a `.lbdb` file.
- Small project: 15 stars, 3 forks, 4 releases (latest June 2026), 2 open issues.
- **Assessment:** meaningfully heavier than the existing approach (which needs zero extra toolchain —
  Python generates a self-contained HTML file, opened via the OS's default browser). Recommend
  sticking with the existing D3 approach for now; revisit if visualization needs actually outgrow it
  (e.g. the LLM cluster-naming feature becomes genuinely wanted, or graphs get too large for a
  hand-rolled force layout to stay usable).

## Related docs

- `tag-graph-real-data-validation.md` — where the `ATTACH` extension gets actually tried.
- `tag-graph-suggestions-and-dedup.md` — where `algo`/`vector` get actually tried.
- `tag-graph-authoritative-driver.md` — why `ATTACH` doesn't solve live sync by itself.
