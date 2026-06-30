from hydrus.core import HydrusConstants as HC

# Forward-only: SQLite stays authoritative, this only keeps the graph's raw SIBLING_OF/PARENT_OF
# edges from drifting too far out of date between one-time imports.
#
# ponytail: IDEAL_OF is deliberately NOT kept live here. It mirrors a closure SQLite itself only
# resolves via its own async 'sync_tag_display_maintenance' loop (a sibling ContentUpdate alone
# doesn't tell us the new ideal -- see TestClientGraphGrounding, which has to call that maintenance
# action before re-reading ideals). Re-running ClientGraphMigrate.ImportFromHydrusDB refreshes
# IDEAL_OF; the plan's own "dirty-marker + re-import as the heal path" covers this. A periodic
# trigger belongs in Phase 2+, once something downstream actually reads IDEAL_OF and cares about
# its freshness -- nothing does yet.
#
# ponytail: only ADD/DELETE are mirrored. PEND/PETITION are repository-sync staging states, not
# changes to the current/displayed graph this mirror represents; re-import heals any drift.

class GraphSync( object ):
    
    def __init__( self, graph_db ):
        
        self._graph_db = graph_db
    
    
    def ProcessContentUpdatePackage( self, content_update_package ):
        
        for ( service_key, content_updates ) in content_update_package.IterateContentUpdates():
            
            for content_update in content_updates:
                
                ( data_type, action, row ) = content_update.ToTuple()
                
                if data_type == HC.CONTENT_TYPE_TAG_SIBLINGS:
                    
                    self._ProcessPair( 'SIBLING_OF', action, row, service_key )
                
                elif data_type == HC.CONTENT_TYPE_TAG_PARENTS:
                    
                    self._ProcessPair( 'PARENT_OF', action, row, service_key )
    
    
    
    
    def _ProcessPair( self, rel_type, action, row, service_key ):
        
        if action == HC.CONTENT_UPDATE_ADD:
            
            ( tag_a, tag_b ) = row
            
            self._graph_db.MergeTag( tag_a )
            self._graph_db.MergeTag( tag_b )
            self._graph_db.MergeEdge( rel_type, tag_a, tag_b, service_key )
        
        elif action == HC.CONTENT_UPDATE_DELETE:
            
            ( tag_a, tag_b ) = row
            
            self._graph_db.DeleteEdge( rel_type, tag_a, tag_b, service_key )


