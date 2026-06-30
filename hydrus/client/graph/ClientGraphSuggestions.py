# Precomputed related-tag suggestions, reading the CO_OCCURS projection ClientGraphProjections
# builds. Same intent as ClientDB._GetRelatedTags (a weighted co-occurrence neighbourhood) but a
# graph lookup against an already-computed projection instead of a time-boxed, statistically-
# sampled search over SQLite mappings each time it's asked.

def GetRelatedTags( graph_db, tag, service_key, limit = 100 ):
    
    ideal = graph_db.GetIdeal( tag, service_key )
    
    # not "related": the tag itself, its canonical form, its ancestors, and anything that's
    # already a known sibling of it -- those are existing relationships, not suggestions
    excluded = { tag, ideal }
    excluded.update( graph_db.GetAncestors( ideal, service_key ) )
    excluded.update( graph_db.GetSiblings( ideal, service_key ) )
    
    
    candidates = graph_db.GetCoOccurring( ideal, service_key, limit = limit + len( excluded ) )
    
    related = [ ( other_tag, count, weight ) for ( other_tag, count, weight ) in candidates if other_tag not in excluded ]
    
    return related[ : limit ]
