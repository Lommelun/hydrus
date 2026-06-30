from hydrus.core import HydrusConstants as HC

from hydrus.client.metadata import ClientTags

# One-time importer: mirrors the tag relationship layer (siblings, parents, and their already-
# resolved ideals/ancestors) out of an existing Hydrus client DB into the graph. Forward-only,
# SQLite stays authoritative -- this is Phase 1, so it reads SQLite's own precomputed closures
# rather than recomputing them (ClientDBTagSiblings/ClientDBTagParents already did that work).
#
# ponytail: no interactive source/priority mapping UI here (the plan mentions one for a later
# migration wizard) -- nothing in Phase 1 consumes tag_sibling_application order yet, so there is
# nothing for it to configure. Add it when the combined-display-ideal question (see below) is
# resolved and something actually reads the order.
#
# ponytail: skips the synthetic 'all known tags' (combined_tag) service. SQLite never computes an
# ideal-siblings cache for it by default (found in Phase 0 -- an upstream gap, not ours), so there
# is no baseline to mirror. Flagged as an open question rather than silently built or silently
# dropped: this only matters once something renders display tags from the graph (Phase 3/4).

def ImportFromHydrusDB( graph_db, hydrus_db ):

    services = [ service for service in hydrus_db.Read( 'services' ) if service.GetServiceType() in HC.REAL_TAG_SERVICES ]

    for service in services:

        graph_db.MergeTagService( service.GetServiceKey(), service.GetServiceType(), service.GetName() )


    service_keys = [ service.GetServiceKey() for service in services ]

    per_service_ideals = {}
    per_service_siblings = {}
    tags = set()
    child_tags = set()  # tags that are a child in at least one service's current parent pairs

    for service_key in service_keys:

        ideals = hydrus_db.Read( 'tag_siblings_all_ideals', service_key )  # { bad_tag : ideal_tag }, non-trivial pairs only
        current_siblings = hydrus_db.Read( 'tag_siblings', service_key )[ HC.CONTENT_STATUS_CURRENT ]
        current_parents = hydrus_db.Read( 'tag_parents', service_key )[ HC.CONTENT_STATUS_CURRENT ]

        per_service_ideals[ service_key ] = ideals
        per_service_siblings[ service_key ] = current_siblings

        tags.update( ideals.keys() )
        tags.update( ideals.values() )

        for ( bad_tag, good_tag ) in current_siblings:

            tags.update( ( bad_tag, good_tag ) )


        for ( child_tag, parent_tag ) in current_parents:

            tags.update( ( child_tag, parent_tag ) )

            child_tags.add( child_tag )



    # Parents/ancestors are NOT mirrored from raw per-service tag_parents pairs: a display
    # service's ancestors are the union of every *applicable* service's parent rules (see
    # ClientDBTagParents.Regen), not just its own. Re-deriving that applicability here would mean
    # reimplementing the precedence engine; instead, mirror SQLite's own already-resolved,
    # cross-service ancestor sets via the same batched read the grounding tests check against.
    ancestor_lookup = hydrus_db.Read( 'tag_siblings_and_parents_lookup', ClientTags.TAG_DISPLAY_DISPLAY_ACTUAL, child_tags ) if len( child_tags ) > 0 else {}

    for ( child_tag, services_to_data ) in ancestor_lookup.items():

        for ( service_key, ( _sibling_chain_members, _ideal_tag, _descendants, ancestors ) ) in services_to_data.items():

            tags.update( ancestors )


    for tag in tags:

        graph_db.MergeTag( tag )


    for service_key in service_keys:

        for ( bad_tag, good_tag ) in per_service_siblings[ service_key ]:

            graph_db.MergeEdge( 'SIBLING_OF', bad_tag, good_tag, service_key )


        for ( bad_tag, ideal_tag ) in per_service_ideals[ service_key ].items():

            graph_db.MergeEdge( 'IDEAL_OF', bad_tag, ideal_tag, service_key )



    # direct edges to every resolved ancestor (not just the immediate parent): SQLite hands us the
    # full per-service ancestor set already, and mirroring it flat keeps GetAncestors correct
    # without needing the tag_parent_application order represented in the graph at all. Trade-off:
    # PARENT_OF here means "is an ancestor of", not strictly "is the immediate parent of" -- fine
    # for ancestor lookups (this Phase's only consumer), but a future chain visualiser wanting
    # clean one-generation-per-hop edges will need a different, service-applicability-aware pass.
    for ( child_tag, services_to_data ) in ancestor_lookup.items():

        for ( service_key, ( _sibling_chain_members, _ideal_tag, _descendants, ancestors ) ) in services_to_data.items():

            for ancestor_tag in ancestors:

                graph_db.MergeEdge( 'PARENT_OF', child_tag, ancestor_tag, service_key )


