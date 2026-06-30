import itertools
import os
import sqlite3
from collections import Counter
from collections import defaultdict

# Batch (re)builders for derived graph data -- the things that have to be recomputed wholesale
# rather than kept live by ClientGraphSync. CO_OCCURS is the only one so far (Phase 2); per the
# plan, this is a periodic full-recompute job, not an incrementally-maintained one.
#
# ponytail: reads SQLite directly for the per-file tag sets, the one deliberate exception to
# "always go through hydrus_db.Read(...)". The plan calls this out explicitly ("CO_OCCURS can be
# derived directly from SQLite") because there's no graph-side per-file data to aggregate from yet
# (TAGGED edges are Phase 4), and no existing Read action does a one-shot bulk per-service mapping
# dump -- the closest, 'migration_get_mappings', is paginated for the GUI's migration wizard, not
# built for a batch job. Opens its own read-only connections (WAL mode supports concurrent
# readers), so this is safe to run alongside the live DB thread.
#
# Caller's responsibility: Hydrus batches commits (does not commit to disk after every write), so
# recent edits may not be visible to these direct-SQLite reads yet. Call controller.db.ForceACommit()
# before this if freshness matters (a periodic idle-maintenance trigger naturally runs well after
# the normal commit cycle, so this mostly matters for an on-demand "rebuild now" caller).

def RebuildCoOccurrence( graph_db, db_dir, service_key, min_count = 2 ):
    
    tag_to_hash_ids = _LoadTagToHashIds( db_dir, service_key )
    
    hash_id_to_tags = defaultdict( set )
    
    for ( tag, hash_ids ) in tag_to_hash_ids.items():
        
        for hash_id in hash_ids:
            
            hash_id_to_tags[ hash_id ].add( tag )
    
    
    num_files = len( hash_id_to_tags )
    
    graph_db.ClearCoOccurs( service_key )
    
    if num_files == 0:
        
        return
    
    
    tag_freq = { tag : len( hash_ids ) for ( tag, hash_ids ) in tag_to_hash_ids.items() }
    
    pair_counts = Counter()
    
    for tags in hash_id_to_tags.values():
        
        for ( a, b ) in itertools.combinations( sorted( tags ), 2 ):
            
            pair_counts[ ( a, b ) ] += 1
    
    
    for ( ( a, b ), count ) in pair_counts.items():
        
        if count < min_count:
            
            continue
        
        
        # lift: count vs. what you'd expect from each tag's standalone frequency alone, so two
        # ultra-common tags (1girl + highres) don't outrank a smaller pair that's actually tied
        expected = ( tag_freq[ a ] * tag_freq[ b ] ) / num_files
        weight = count / expected if expected > 0 else 0.0
        
        graph_db.MergeTag( a )
        graph_db.MergeTag( b )
        graph_db.MergeCoOccurs( a, b, service_key, count, weight )



def _LoadTagToHashIds( db_dir, service_key ):
    
    client_db_path = os.path.join( db_dir, 'client.db' )
    mappings_db_path = os.path.join( db_dir, 'client.mappings.db' )
    master_db_path = os.path.join( db_dir, 'client.master.db' )
    
    client_conn = sqlite3.connect( f'file:{client_db_path}?mode=ro', uri = True )
    
    service_id_row = client_conn.execute( 'SELECT service_id FROM services WHERE service_key = ?', ( service_key, ) ).fetchone()
    
    client_conn.close()
    
    if service_id_row is None:
        
        return {}
    
    
    ( service_id, ) = service_id_row
    
    mappings_conn = sqlite3.connect( f'file:{mappings_db_path}?mode=ro', uri = True )
    
    tag_id_to_hash_ids = defaultdict( set )
    
    for ( tag_id, hash_id ) in mappings_conn.execute( f'SELECT tag_id, hash_id FROM current_mappings_{service_id}' ):
        
        tag_id_to_hash_ids[ tag_id ].add( hash_id )
    
    
    mappings_conn.close()
    
    master_conn = sqlite3.connect( f'file:{master_db_path}?mode=ro', uri = True )
    
    namespaces = dict( master_conn.execute( 'SELECT namespace_id, namespace FROM namespaces' ) )
    subtags = dict( master_conn.execute( 'SELECT subtag_id, subtag FROM subtags' ) )
    
    tag_id_to_tag = {}
    
    for ( tag_id, namespace_id, subtag_id ) in master_conn.execute( 'SELECT tag_id, namespace_id, subtag_id FROM tags' ):
        
        namespace = namespaces.get( namespace_id, '' )
        subtag = subtags.get( subtag_id, '' )
        
        tag_id_to_tag[ tag_id ] = f'{namespace}:{subtag}' if namespace else subtag
    
    
    master_conn.close()
    
    return { tag_id_to_tag[ tag_id ] : hash_ids for ( tag_id, hash_ids ) in tag_id_to_hash_ids.items() if tag_id in tag_id_to_tag }
