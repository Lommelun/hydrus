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

## Concurrency & connections (`docs.ladybugdb.com/concurrency/`) — re-verified rigorously 2026-07-01

The docs' own wording is broader/scarier than the actual enforced behavior — re-tested with a true
two-*process* setup (not just two connections in one script) specifically to resolve the discrepancy:
one OS process holding a `READ_WRITE` connection and **actively writing in a loop** (not just idle),
while a second, separate OS process attempted concurrent access.

- **`ladybug.Database(path, read_only=True)` from a separate process works concurrently alongside an
  actively-writing separate process** — confirmed: real data returned, correct row count, no error,
  while the writer process was verifiably still running and actively executing writes throughout.
- **A second `READ_WRITE` connection from a separate process correctly fails**, with exactly the error
  the docs describe: `RuntimeError: IO exception: Could not set lock on file ... Lock is held by PID
  <n>`. This is the real, enforced single-writer boundary — read-vs-write, not "any second connection."
- **One nuance worth knowing:** in an earlier, less rigorous version of this same test — writer process
  opens a `Connection` but never calls `.execute()` before a second `READ_WRITE` connection attempts to
  open — the second connection succeeded without error. This suggests the write lock may be acquired
  lazily (tied to the first actual write, not to `Connection()` construction) rather than always held
  from the moment a `READ_WRITE` `Database`/`Connection` object exists. Not fully characterized; the
  practical takeaway (a genuinely active writer correctly blocks a second writer, and never blocks a
  reader) is what matters for this project and is now confirmed solidly.
- **Bottom line for this project:** the existing pattern (a live `ClientGraphController` holding the
  one `READ_WRITE` connection; occasional external read-only inspection via a separate connection, e.g.
  for dev verification) is safe and correctly supported. Never open a second `READ_WRITE` connection to
  the same graph path while the app is running — that's the one real boundary.

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

## Extension: SQLite attach (`docs.ladybugdb.com/extensions/attach/sqlite/`) — hands-on tested 2026-07-01

Basic mechanics confirmed against a synthetic 2-file SQLite database mirroring Hydrus's real
`client.mappings.db`/`client.master.db` split (a scratch spike, not committed code):

```
LOAD sqlite;                                    -- must run once per Connection session, not persisted
                                                 -- at the database level (confirmed: a fresh Connection
                                                 -- to the same on-disk graph needs this again)
ATTACH 'mappings.db' AS m (dbtype sqlite);
ATTACH 'master.db' AS mst (dbtype sqlite);       -- multiple simultaneous attaches work fine
```

**What works, confirmed by direct testing, not just docs:**
- **Cross-attached-source JOINs work**, via chained `LOAD FROM` + `WITH`-renaming to dodge column-name
  collisions (a bare `WHERE tag_id = tag_id` self-collides if both tables have a `tag_id` column):
  ```
  LOAD FROM m.current_mappings_7
  WITH tag_id AS m_tag_id, hash_id AS m_hash_id
  LOAD FROM mst.tags
  WHERE tag_id = m_tag_id
  RETURN m_hash_id, subtag_id
  ```
  Verified this returns the correct joined rows against known synthetic data. This means the earlier
  hedge ("no confirmed single-query join") was too pessimistic for attached-source-to-attached-source
  joins specifically — it works, just not with plain SQL subquery syntax (`LOAD FROM (SELECT ...)`
  fails to parse; must use this chained Cypher-native form).
- **`COPY NativeTable FROM (LOAD FROM ... RETURN ...)` works** — loads straight into a native Ladybug
  table from a `LOAD FROM` subquery, **no intermediate CSV file at all**. Confirmed.
- **BLOB columns pass through natively** (`RETURN hash AS sha256` where `hash` is a SQLite BLOB column,
  into a native `BLOB`-typed property) — this sidesteps needing any hex-encoding function entirely,
  since `hex()`/`to_hex()`/`bin_to_hex()`/`encode()` are **not available functions** in this Ladybug
  build (`CAST(blob AS STRING)` exists but produces a Python-repr-style escaped string, not usable as a
  clean hex string, e.g. `\xAA\xAA...` not `aaaa...`).

**What does NOT work, confirmed by direct testing (a real, silent-failure footgun):**
- **Anti-join filtering (`OPTIONAL MATCH ... WHERE existing IS NULL` against an already-populated
  native table, combined with a `LOAD FROM` attached source) does not reliably filter** — it silently
  returned all rows, including ones that should have been excluded, rather than erroring. This was
  only caught because the follow-up `COPY` then failed on a duplicate primary key it should never have
  seen. **This is a real correctness trap**, not just a missing feature — if you rely on this pattern
  to implement "only load new rows," it will silently corrupt or fail your data load rather than
  cleanly filtering. Do not use this pattern without re-verifying it first.
- Practical consequence: since `COPY` still fails the whole batch on any duplicate primary key (see
  above), and there's no working way to filter attached-source rows against already-graphed rows in
  pure Cypher, **the "only load rows that aren't already in the graph" logic that makes rebuilds
  idempotent still has to happen in Python** (fetch existing IDs, fetch source IDs, set-difference,
  then load only the new subset) — attach doesn't eliminate this step.

**Performance: `UNWIND $list AS x CREATE (...)` (parameterized bulk insert, no CSV, no attach) was
also benchmarked as a third option**, since it could sidestep the anti-join gap entirely (filter in
Python, pass the filtered list as a query parameter, skip both the CSV file and the attach machinery).
Head-to-head at the same scale as the original CO_OCCURS benchmark (71,356 edges):
- **CSV + `COPY`** (current production approach): **0.082s** total (tags + edges).
- **`UNWIND` + `CREATE`** for the same edges: **1.975s** — ~24x slower than CSV+`COPY` for
  relationships specifically, because each edge needs a per-row `MATCH` to find its two endpoint nodes
  by primary key before creating it, which `COPY`'s bulk-loader path skips entirely. (For *node*
  creation alone, `UNWIND`+`CREATE` was fast — 0.009s for 3,000 nodes — comparable to `COPY`; the gap
  is specifically in relationship loading, which is the expensive, dominant part of this project's
  actual workloads.)
- **Verdict: CSV + `COPY` remains clearly the fastest option for bulk relationship loading.** Neither
  attach-based loading nor `UNWIND`+`CREATE` beats it; both were real candidates worth testing, both
  lost decisively once actually measured.

**Overall verdict (2026-07-01): evaluated for real, not adopted.** Attach-based loading could
genuinely simplify the *read* side of `ClientGraphProjections.py`'s `_LoadTagToHashIds` (replacing
three separate Python `sqlite3.connect()` calls + manual dict-based tag_id→string joining with one
chained `LOAD FROM` query) — that part is a real, working capability now. But: (a) it doesn't improve
performance anywhere it matters (the bulk relationship load, which is the actual cost, stays on CSV+
`COPY` either way, unchanged); (b) it adds a new runtime extension dependency (`LOAD sqlite;`,
currently unused by any shipped code) for zero performance gain; (c) it trades legible,
boring, well-understood Python (`sqlite3` + a dict comprehension) for less-familiar Cypher syntax with
at least one confirmed silent-failure footgun nearby (the anti-join case) in the same feature area.
**Recommendation: don't adopt this for the already-shipped, already-tested `ClientGraphProjections.py`
code.** The finding is worth keeping (settles the open question with hard data instead of speculation,
and the JOIN/BLOB/COPY-without-CSV capabilities are useful facts if this ever comes up again in a
different context), but it doesn't clear the bar of being a clear win over what's already working.

## Bulk import formats & Parquet — hands-on tested 2026-07-01

`docs.ladybugdb.com/import/` confirms `COPY FROM` (not `CREATE`/`MERGE`) is the intended bulk-load
mechanism for "larger graphs of millions of nodes and beyond" — matches what this project already
does. Supported formats: CSV, **Parquet**, NumPy, JSON, Pandas/Polars/PyArrow DataFrames, subqueries.
Also notes an automatic spill-to-disk mechanism for 100M+ scale relationship tables (memory
management, not something this project's current scale needs to think about, but relevant context for
`tag-graph-authoritative-driver.md`'s PTR-scale question).

**Parquet export/import syntax** (`docs.ladybugdb.com/export/parquet/`):
```
COPY (MATCH (u:User) RETURN u.*) TO 'user.parquet' (compression = 'snappy');   -- export
LOAD FROM 'user.parquet' RETURN *;                                            -- import/scan
COPY SomeTable FROM 'user.parquet';                                           -- import into native table
```

**Real end-to-end benchmark** (Python writes the file, then Ladybug `COPY`s it in — the actual
production shape, not just Ladybug-to-Ladybug): tested via an isolated scratch venv with `pyarrow`
(not installed in this project's real venv), comparing the full pipeline
(`csv.writer`+`COPY FROM csv` vs. `pyarrow.parquet.write_table`+`COPY FROM parquet`) at two scales:

| Edges | CSV pipeline | Parquet pipeline | Winner |
|---|---|---|---|
| 71,356 (matches the original CO_OCCURS benchmark scale) | 0.055s | 0.066s | CSV, narrowly |
| 1,500,000 (~20x larger, closer to a real-DB order of magnitude) | 1.062s | 0.819s | **Parquet, 1.30x faster** |

**Interpretation:** Parquet has real fixed overhead (columnar/binary structure, compression setup)
that doesn't pay off at small scale — CSV wins narrowly at today's dev-scale corpus size. But the
advantage grows with data size (crosses over somewhere between 71k and 1.5M edges) and file size drops
sharply (Parquet was ~5x smaller than CSV for the same data at the 1.5M-edge test). **Not adopted now**
— zero benefit at the project's current actual scale, and it would add `pyarrow` (a substantial
dependency) for a win that doesn't materialize yet. **Worth trying for real** once
`tag-graph-real-data-validation.md`'s real-scale data is in and *if* CSV import time actually shows up
as a bottleneck at that point — this is exactly the kind of thing to revisit with real numbers, not
speculation, at that time.

## Migration between Ladybug versions (`docs.ladybugdb.com/migrate/`)

**Not about migrating from SQLite or another database** — despite the URL, this page covers migrating
data between different *versions of Ladybug itself* (schema evolution across upgrades), via
`EXPORT DATABASE` (dumps schema + data, with a `schema_only = true` option) and `IMPORT DATABASE` on
the new version. Relevant context for this project's own noted risk ("Ladybug (young fork) holds the
only copy post-flip" in the durability considerations) — there's a documented, supported path for
carrying data forward across Ladybug upgrades, which somewhat de-risks that concern, though it hasn't
been tested hands-on since this project hasn't needed a version migration yet.

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

- `tag-graph-real-data-validation.md` — where `ATTACH` was tried (verdict: no) and where Parquet is
  worth trying for real, at real scale, if CSV import time turns out to matter there.
- `tag-graph-suggestions-and-dedup.md` — where `algo`/`vector` get actually tried.
- `tag-graph-authoritative-driver.md` — why `ATTACH` doesn't solve live sync by itself.
