from hydrus.core import HydrusConstants as HC

# One-time importer: mirrors the tag relationship layer (siblings, parents, and their already-
# resolved ideals) out of an existing Hydrus client DB into the graph. Forward-only, SQLite stays
# authoritative -- this is Phase 1, so it reads SQLite's own precomputed closures rather than
# recomputing them (ClientDBTagSiblings/ClientDBTagParents already did that work).
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
    
    
    for service in services:
        
        service_key = service.GetServiceKey()
        
        ideals = hydrus_db.Read( 'tag_siblings_all_ideals', service_key )  # { bad_tag : ideal_tag }, non-trivial pairs only
        
        current_siblings = hydrus_db.Read( 'tag_siblings', service_key )[ HC.CONTENT_STATUS_CURRENT ]
        current_parents = hydrus_db.Read( 'tag_parents', service_key )[ HC.CONTENT_STATUS_CURRENT ]
        
        tags = set( ideals.keys() ) | set( ideals.values() )
        
        for ( bad_tag, good_tag ) in current_siblings:
            
            tags.update( ( bad_tag, good_tag ) )
        
        
        for ( child_tag, parent_tag ) in current_parents:
            
            tags.update( ( child_tag, parent_tag ) )
        
        
        for tag in tags:
            
            graph_db.MergeTag( tag )
        
        
        for ( bad_tag, good_tag ) in current_siblings:
            
            graph_db.MergeEdge( 'SIBLING_OF', bad_tag, good_tag, service_key )
        
        
        for ( bad_tag, ideal_tag ) in ideals.items():
            
            graph_db.MergeEdge( 'IDEAL_OF', bad_tag, ideal_tag, service_key )
        
        
        # parents sit between ideals: Hydrus idealises parent pairs through siblings before display
        # (ClientDBTagParents.Regen -> IdealiseStatusesToPairIds), so we mirror that same collapse
        # here rather than storing raw, pre-sibling parent pairs.
        for ( child_tag, parent_tag ) in current_parents:
            
            idealised_child = ideals.get( child_tag, child_tag )
            idealised_parent = ideals.get( parent_tag, parent_tag )
            
            graph_db.MergeEdge( 'PARENT_OF', idealised_child, idealised_parent, service_key )


