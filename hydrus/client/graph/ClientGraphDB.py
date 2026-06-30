from hydrus.core import HydrusTags

# Phase 1 was the relationship layer (Tag, TagService, SIBLING_OF, IDEAL_OF, PARENT_OF). Phase 2
# added CO_OCCURS, derived directly from SQLite mappings. Phase 4a adds File + TAGGED: a duplicate,
# read-only mirror of SQLite's current file->tag mappings, for cross-checking only -- nothing
# downstream reads it yet (see ClientGraphProjections.RebuildFileTags).

SCHEMA_STATEMENTS = [
    'CREATE NODE TABLE IF NOT EXISTS Tag(tag STRING, namespace STRING, subtag STRING, PRIMARY KEY(tag))',
    'CREATE NODE TABLE IF NOT EXISTS TagService(service_key STRING, service_type INT64, name STRING, PRIMARY KEY(service_key))',
    'CREATE NODE TABLE IF NOT EXISTS File(hash_id INT64, sha256 STRING, PRIMARY KEY(hash_id))',
    'CREATE REL TABLE IF NOT EXISTS SIBLING_OF(FROM Tag TO Tag, service_key STRING)',
    'CREATE REL TABLE IF NOT EXISTS IDEAL_OF(FROM Tag TO Tag, service_key STRING)',
    'CREATE REL TABLE IF NOT EXISTS PARENT_OF(FROM Tag TO Tag, service_key STRING)',
    'CREATE REL TABLE IF NOT EXISTS CO_OCCURS(FROM Tag TO Tag, service_key STRING, count INT64, weight DOUBLE)',
    'CREATE REL TABLE IF NOT EXISTS TAGGED(FROM File TO Tag, service_key STRING)',
]

class GraphDB( object ):
    
    def __init__( self, db_dir: str ):
        
        import ladybug
        
        # ponytail: no os.makedirs here -- ladybug creates/opens its own directory at this path
        # and errors if it already exists as a plain (non-ladybug) directory.
        self._database = ladybug.Database( db_dir )
        self._connection = ladybug.Connection( self._database )
        
        for statement in SCHEMA_STATEMENTS:
            
            self._connection.execute( statement )
    
    
    
    def IsEmpty( self ) -> bool:
        
        result = self._connection.execute( 'MATCH (t:Tag) RETURN count(t)' )
        
        return result.get_next()[ 0 ] == 0
    
    
    def Execute( self, query: str, parameters = None ):
        
        return self._connection.execute( query, parameters )
    
    
    def MergeTagService( self, service_key: bytes, service_type: int, name: str ):
        
        self._connection.execute(
            'MERGE (s:TagService {service_key: $service_key}) ON CREATE SET s.service_type = $service_type, s.name = $name ON MATCH SET s.service_type = $service_type, s.name = $name',
            { 'service_key' : service_key.hex(), 'service_type' : service_type, 'name' : name }
        )
    
    
    def MergeTag( self, tag: str ):
        
        ( namespace, subtag ) = HydrusTags.SplitTag( tag )
        
        self._connection.execute(
            'MERGE (t:Tag {tag: $tag}) ON CREATE SET t.namespace = $namespace, t.subtag = $subtag',
            { 'tag' : tag, 'namespace' : namespace, 'subtag' : subtag }
        )
    
    
    def MergeEdge( self, rel_type: str, tag_a: str, tag_b: str, service_key: bytes ):
        
        if rel_type not in ( 'SIBLING_OF', 'IDEAL_OF', 'PARENT_OF' ):
            
            raise ValueError( f'Unknown graph rel type: {rel_type}' )
        
        
        self._connection.execute(
            f'MATCH (a:Tag {{tag: $tag_a}}), (b:Tag {{tag: $tag_b}}) MERGE (a)-[:{rel_type} {{service_key: $service_key}}]->(b)',
            { 'tag_a' : tag_a, 'tag_b' : tag_b, 'service_key' : service_key.hex() }
        )
    
    
    def DeleteEdge( self, rel_type: str, tag_a: str, tag_b: str, service_key: bytes ):
        
        if rel_type not in ( 'SIBLING_OF', 'IDEAL_OF', 'PARENT_OF' ):
            
            raise ValueError( f'Unknown graph rel type: {rel_type}' )
        
        
        self._connection.execute(
            f'MATCH (a:Tag {{tag: $tag_a}})-[r:{rel_type} {{service_key: $service_key}}]->(b:Tag {{tag: $tag_b}}) DELETE r',
            { 'tag_a' : tag_a, 'tag_b' : tag_b, 'service_key' : service_key.hex() }
        )
    
    
    def GetExistingTags( self ) -> set:
        
        result = self._connection.execute( 'MATCH (t:Tag) RETURN t.tag' )
        
        tags = set()
        
        while result.has_next():
            
            tags.add( result.get_next()[ 0 ] )
        
        
        return tags
    
    
    def GetExistingFileHashIds( self ) -> set:
        
        result = self._connection.execute( 'MATCH (f:File) RETURN f.hash_id' )
        
        hash_ids = set()
        
        while result.has_next():
            
            hash_ids.add( result.get_next()[ 0 ] )
        
        
        return hash_ids
    
    
    def ClearFileTags( self, service_key: bytes ):
        
        self._connection.execute(
            'MATCH (:File)-[r:TAGGED {service_key: $service_key}]->(:Tag) DELETE r',
            { 'service_key' : service_key.hex() }
        )
    
    
    def BulkLoad( self, table_name: str, csv_path: str ):
        
        # PARALLEL=FALSE: the default parallel CSV reader chokes on quoted newlines, which a tag
        # could in principle contain; not worth the speed for the rare case it bites
        self._connection.execute( f'COPY {table_name} FROM "{csv_path}" (HEADER=true, PARALLEL=FALSE)' )
    
    
    def ClearCoOccurs( self, service_key: bytes ):
        
        self._connection.execute(
            'MATCH (:Tag)-[r:CO_OCCURS {service_key: $service_key}]->(:Tag) DELETE r',
            { 'service_key' : service_key.hex() }
        )
    
    
    def GetCoOccurring( self, tag: str, service_key: bytes, limit: int = 100 ) -> list:
        
        result = self._connection.execute(
            'MATCH (a:Tag {tag: $tag})-[r:CO_OCCURS {service_key: $service_key}]-(b:Tag) RETURN b.tag, r.count, r.weight ORDER BY r.weight DESC LIMIT $limit',
            { 'tag' : tag, 'service_key' : service_key.hex(), 'limit' : limit }
        )
        
        rows = []
        
        while result.has_next():
            
            rows.append( result.get_next() )
        
        
        return rows
    
    
    def GetIdeal( self, tag: str, service_key: bytes ) -> str:
        
        result = self._connection.execute(
            'MATCH (a:Tag {tag: $tag})-[r:IDEAL_OF {service_key: $service_key}]->(b:Tag) RETURN b.tag',
            { 'tag' : tag, 'service_key' : service_key.hex() }
        )
        
        if result.has_next():
            
            return result.get_next()[ 0 ]
        
        
        return tag
    
    
    def GetAncestors( self, tag: str, service_key: bytes ) -> set:
        
        result = self._connection.execute(
            'MATCH (a:Tag {tag: $tag})-[:PARENT_OF* {service_key: $service_key}]->(b:Tag) RETURN DISTINCT b.tag',
            { 'tag' : tag, 'service_key' : service_key.hex() }
        )
        
        ancestors = set()
        
        while result.has_next():
            
            ancestors.add( result.get_next()[ 0 ] )
        
        
        return ancestors
    
    
    def Close( self ):
        
        del self._connection
        del self._database


