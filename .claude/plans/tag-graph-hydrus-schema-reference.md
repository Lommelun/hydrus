# Reference: Hydrus SQLite tag schema & display-resolution mechanics

Pure facts about how Hydrus stores and resolves tags in SQLite, gathered while researching the
opt-in Ladybug tag-graph backend project (see `tag-graph-index.md`). No task framing here — this is
background any of the task docs may need, kept in one place instead of re-explained per doc.

## Storage tables (the raw data)

- **Tag master** (`client.master.db`): `namespaces` (namespace_id, namespace), `subtags` (subtag_id,
  subtag), `tags` (tag_id, namespace_id, subtag_id). A tag's display string is `namespace:subtag` or
  just `subtag` if no namespace.
- **Per-service mappings** (`client.mappings.db`): `current_mappings_{service_id}`,
  `deleted_mappings_{service_id}`, `pending_mappings_{service_id}`, `petitioned_mappings_{service_id}`
  — each `(tag_id, hash_id)` pairs, one table set per tag service. This is what
  `ClientGraphProjections.RebuildFileTags` mirrors directly — **storage-level**, raw, no sibling/parent
  collapsing.
- **Siblings** (`ClientDBTagSiblings.py`): raw bad→good pairs per service, plus a precomputed
  `ideal_tag_siblings_lookup_cache_{service_id}` (closure already resolved to the canonical/ideal tag).
- **Parents** (`ClientDBTagParents.py`): raw child→parent pairs per service, plus precomputed ancestor
  caches.
- **Hashes** (`client.master.db`): `hashes` table, `hash_id INTEGER PRIMARY KEY, hash BLOB_BYTES
  UNIQUE` — the sha256, joined to everything else by `hash_id`.

## The storage vs. display distinction (the single most important fact for any graph work that
touches search or counts)

Hydrus has two "tag display types," `ClientTags.TAG_DISPLAY_STORAGE` and
`ClientTags.TAG_DISPLAY_DISPLAY_ACTUAL`:

- **Storage**: the raw tag as literally applied to a file on a given service. What you see in the
  tagging ("write") autocomplete box.
- **Display**: what search and the "read" autocomplete box actually show/match — sibling-collapsed
  (a bad tag displays as its ideal) **and parent-implied** (a file also matches searches for its tags'
  ancestors). This is computed by `ClientDBTagDisplay.GetImplies`, confirmed by direct read:

  ```python
  def GetImplies( self, display_type, tag_service_id, tag_id ) -> set[ int ]:
      # a tag implies its ideal sibling and any ancestors
      ideal_tag_id = self.modules_tag_siblings.GetIdealTagId( display_type, tag_service_id, tag_id )
      implies = { ideal_tag_id }
      implies.update( self.modules_tag_parents.GetAncestors( display_type, tag_service_id, ideal_tag_id ) )
      return implies
  ```

  Concretely: tagging a file `cat` also makes it match a search for `animal`, if `cat`→`animal` is a
  parent chain (possibly via an intermediate like `feline`).

- **SQLite does not compute this live at query time.** It's denormalized into maintained cache
  tables — `cache_current_display_mappings_{file_service}_{tag_service}` (see
  `ClientDBMappingsStorage.GenerateSpecificDisplayMappingsCacheTableNames`), queried directly by
  `ClientDBFilesSearch.GetHashIdsFromTag` (line ~408) via `GetIdealTagId` → `GetChainMembersFromIdeal`
  → a lookup against that cache table — not a live graph-walk over raw mappings.
- **Any graph work that needs to match SQLite's search/count semantics needs the *display* version of
  this, not the storage version.** The existing `ClientGraphProjections.RebuildFileTags` mirror is
  storage-level only (raw `current_mappings_{service_id}`) — it cannot back a search-equivalent or
  `system:number of tags`-equivalent feature without silently dropping parent-implied matches. This is
  the reason `tag-graph-query-resolution.md` needs a *new*, separate display-level projection.

## Ordering / precedence: `tag_display_application`

Hydrus supports multiple tag services contributing to one display view (e.g. the user's real setup:
`source → PTR → personal` precedence). This is configured, not inferred: table
`tag_sibling_application(master_service_id, service_index, application_service_id)` (and a parent
twin) lists, per *display* service, which other services' siblings/parents apply and in what order.
`GetIdealTagId(display_type, service_id, tag_id)` resolves a tag's canonical form for a given display
service under that order. The existing graph importer (`ClientGraphMigrate.ImportFromHydrusDB`)
already mirrors this correctly by reading SQLite's own already-resolved
`tag_siblings_all_ideals`/`tag_siblings_and_parents_lookup` outputs rather than raw per-service pairs
— confirmed via a dedicated cross-service test
(`TestClientGraph.TestClientGraphMigration.test_importer_matches_sqlite_ancestors_under_cross_service_application_order`).

## Counts (used by autocomplete and `system:number of tags`)

Also precomputed and denormalized, in `ClientDBMappingsCounts.py`: separate cache tables per
`(file_service, tag_service, tag_display_type)`, e.g.
`cache_current_display_mappings_counts_cache_{file_service}_{tag_service}` (display) vs.
`cache_current_mappings_counts_cache_{file_service}_{tag_service}` (storage). A query returns
`(current_count, pending_count)` directly from the cache — not computed at query time. This is why
autocomplete is already fast without a graph backend (see
`tag-graph-search-pipeline-reference.md`).

## Related docs

- `tag-graph-search-pipeline-reference.md` — how these tables get combined into a file search result.
- `tag-graph-query-resolution.md` — the task that needs a display-level graph projection built on
  these facts.
