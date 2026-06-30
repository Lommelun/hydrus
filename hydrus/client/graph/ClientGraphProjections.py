import csv
import itertools
import os
import sqlite3
import tempfile
from collections import Counter
from collections import defaultdict

from hydrus.core import HydrusTags

# Batch (re)builders for derived graph data -- the things that have to be recomputed wholesale
# rather than kept live by ClientGraphSync. CO_OCCURS is the only one so far (Phase 2); per the
# plan, this is a periodic full-recompute job, not an incrementally-maintained one.
#
# ponytail: reads SQLite directly for the per-file tag sets, the one deliberate exception to
# "always go through hydrus_db.Read(...)". The plan calls this out explicitly ("CO_OCCURS can be
# derived directly from SQLite") because no existing Read action does a one-shot bulk per-service
# mapping dump -- the closest, 'migration_get_mappings', is paginated for the GUI's migration
# wizard, not built for a batch job. Opens its own read-only connections (WAL mode supports
# concurrent readers), so this is safe to run alongside the live DB thread.
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
    
    
    pruned_pairs = []
    involved_tags = set()
    
    for ( ( a, b ), count ) in pair_counts.items():
        
        if count < min_count:
            
            continue
        
        
        # lift: count vs. what you'd expect from each tag's standalone frequency alone, so two
        # ultra-common tags (1girl + highres) don't outrank a smaller pair that's actually tied
        expected = ( tag_freq[ a ] * tag_freq[ b ] ) / num_files
        weight = count / expected if expected > 0 else 0.0
        
        pruned_pairs.append( ( a, b, count, weight ) )
        involved_tags.add( a )
        involved_tags.add( b )
    
    
    if len( pruned_pairs ) == 0:
        
        return
    
    
    # bulk CSV load, not per-edge MERGE: a real corpus prunes down to tens of thousands of pairs
    # or more, and per-row Cypher execute() is ~10,000x slower than COPY at that volume (measured:
    # 71k edges, 607s with MERGE vs 0.05s with COPY)
    with tempfile.TemporaryDirectory( prefix = 'hydrus_graph_cooccur_' ) as tmp_dir:
        
        _BulkLoadNewTags( graph_db, involved_tags, tmp_dir )
        
        edges_csv_path = os.path.join( tmp_dir, 'edges.csv' )
        
        with open( edges_csv_path, 'w', newline = '', encoding = 'utf8' ) as f:
            
            writer = csv.writer( f )
            writer.writerow( [ 'tag_a', 'tag_b', 'service_key', 'count', 'weight' ] )
            
            for ( a, b, count, weight ) in pruned_pairs:
                
                writer.writerow( [ a, b, service_key.hex(), count, weight ] )
        
        
        graph_db.BulkLoad( 'CO_OCCURS', edges_csv_path )



# Phase 4a: load File (hash-identity) + TAGGED edges into the graph as a duplicate, read-only
# mirror of SQLite's current mappings -- the same data SQLite already has, not a switch. SQLite
# stays authoritative; this exists purely so graph-derived results can be cross-checked against it
# (see TestClientGraphProjections.py) before anything is built that actually relies on it (Phase 4b).
# Storage tags only (current_mappings, like RebuildCoOccurrence) -- not sibling/parent-collapsed
# display tags, so cross-checks must compare against SQLite's own storage-level counts, not a
# display-tag Read action.

def RebuildFileTags( graph_db, db_dir, service_key ):
    
    tag_to_hash_ids = _LoadTagToHashIds( db_dir, service_key )
    
    graph_db.ClearFileTags( service_key )
    
    if len( tag_to_hash_ids ) == 0:
        
        return
    
    
    all_hash_ids = set()
    
    for hash_ids in tag_to_hash_ids.values():
        
        all_hash_ids.update( hash_ids )
    
    
    new_hash_ids = all_hash_ids - graph_db.GetExistingFileHashIds()
    
    # ponytail: assumes every hash_id in current_mappings has a row in master's hashes table.
    # True for any DB that hasn't hit the rare orphan-hash_id recovery path in ClientDBMaster --
    # not worth guarding against here until a real-DB run actually trips it.
    hash_id_to_sha256 = _LoadHashes( db_dir, new_hash_ids )
    
    with tempfile.TemporaryDirectory( prefix = 'hydrus_graph_filetags_' ) as tmp_dir:
        
        _BulkLoadNewTags( graph_db, set( tag_to_hash_ids.keys() ), tmp_dir )
        
        if len( new_hash_ids ) > 0:
            
            files_csv_path = os.path.join( tmp_dir, 'files.csv' )
            
            with open( files_csv_path, 'w', newline = '', encoding = 'utf8' ) as f:
                
                writer = csv.writer( f )
                writer.writerow( [ 'hash_id', 'sha256' ] )
                
                for hash_id in new_hash_ids:
                    
                    writer.writerow( [ hash_id, hash_id_to_sha256[ hash_id ].hex() ] )
            
            
            graph_db.BulkLoad( 'File', files_csv_path )
        
        
        tagged_csv_path = os.path.join( tmp_dir, 'tagged.csv' )
        
        with open( tagged_csv_path, 'w', newline = '', encoding = 'utf8' ) as f:
            
            writer = csv.writer( f )
            writer.writerow( [ 'hash_id', 'tag', 'service_key' ] )
            
            for ( tag, hash_ids ) in tag_to_hash_ids.items():
                
                for hash_id in hash_ids:
                    
                    writer.writerow( [ hash_id, tag, service_key.hex() ] )
        
        
        graph_db.BulkLoad( 'TAGGED', tagged_csv_path )



def _BulkLoadNewTags( graph_db, tags, tmp_dir ):
    
    new_tags = set( tags ) - graph_db.GetExistingTags()
    
    if len( new_tags ) == 0:
        
        return
    
    
    tags_csv_path = os.path.join( tmp_dir, 'tags.csv' )
    
    with open( tags_csv_path, 'w', newline = '', encoding = 'utf8' ) as f:
        
        writer = csv.writer( f )
        writer.writerow( [ 'tag', 'namespace', 'subtag' ] )
        
        for tag in new_tags:
            
            ( namespace, subtag ) = HydrusTags.SplitTag( tag )
            
            writer.writerow( [ tag, namespace, subtag ] )
    
    
    graph_db.BulkLoad( 'Tag', tags_csv_path )



def _LoadHashes( db_dir, hash_ids ):
    
    if len( hash_ids ) == 0:
        
        return {}
    
    
    master_db_path = os.path.join( db_dir, 'client.master.db' )
    
    master_conn = sqlite3.connect( f'file:{master_db_path}?mode=ro', uri = True )
    
    hash_id_to_sha256 = { hash_id : sha256 for ( hash_id, sha256 ) in master_conn.execute( 'SELECT hash_id, hash FROM hashes' ) if hash_id in hash_ids }
    
    master_conn.close()
    
    return hash_id_to_sha256



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
