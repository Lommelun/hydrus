import json
import os
import shutil
import tempfile
import unittest

from hydrus.client.graph import ClientGraphDB
from hydrus.client.graph import ClientGraphMigrate
from hydrus.client.graph import ClientGraphProjections
from hydrus.client.graph import ClientGraphVisualize

from hydrus.test import ClientGraphTestFixtures
from hydrus.test import TestController

# BuildNeighborhood/GenerateHTML operate on a graph built straight from the grounding fixture's
# known sibling/parent/co-occurrence layout (see ClientGraphTestFixtures and
# TestClientGraphGrounding's own assertions for what that layout is) -- so what to expect here is
# exact, not approximate.

class TestClientGraphVisualize( ClientGraphTestFixtures.GraphFixtureMixin, unittest.TestCase ):
    
    def test_build_neighborhood_from_grounding_fixture( self ):
        
        self._BuildFixture()
        
        type( self )._db.ForceACommit()
        
        graph_parent_dir = tempfile.mkdtemp( prefix = 'hydrus_graph_visualize_' )
        graph_dir = os.path.join( graph_parent_dir, 'graph' )
        
        try:
            
            graph_db = ClientGraphDB.GraphDB( graph_dir )
            
            ClientGraphMigrate.ImportFromHydrusDB( graph_db, type( self )._db )
            ClientGraphProjections.RebuildCoOccurrence( graph_db, TestController.DB_DIR, self.personal_key, min_count = 1 )
            
            neighborhood = ClientGraphVisualize.BuildNeighborhood( graph_db, 'cat', self.personal_key )
            
            self.assertEqual( neighborhood[ 'seed' ], 'cat' )
            self.assertIn( 'cat', neighborhood[ 'nodes' ] )
            self.assertIn( 'feline', neighborhood[ 'nodes' ] ) # ancestor
            self.assertIn( 'animal', neighborhood[ 'nodes' ] ) # transitive ancestor, already flattened
            self.assertIn( 'outdoors', neighborhood[ 'nodes' ] ) # co-occurring
            
            edge_types = { ( e[ 'source' ], e[ 'target' ], e[ 'type' ] ) for e in neighborhood[ 'edges' ] }
            
            self.assertIn( ( 'cat', 'feline', 'PARENT_OF' ), edge_types )
            self.assertIn( ( 'cat', 'animal', 'PARENT_OF' ), edge_types )
            
            co_occurs_targets = { e[ 'target' ] for e in neighborhood[ 'edges' ] if e[ 'type' ] == 'CO_OCCURS' and e[ 'source' ] == 'cat' }
            
            self.assertIn( 'outdoors', co_occurs_targets )
            
            html_text = ClientGraphVisualize.GenerateHTML( neighborhood )
            
            self.assertIn( '<svg>', html_text )
            self.assertIn( 'cat', html_text )
            
            # the embedded DATA blob must be the one well-formed JSON object in the page -- pull it
            # back out and parse it for real, rather than just string-matching on fragments
            start = html_text.index( 'const DATA = ' ) + len( 'const DATA = ' )
            end = html_text.index( ';\n', start )
            parsed = json.loads( html_text[ start : end ] )
            
            self.assertEqual( parsed[ 'seed' ], 'cat' )
            self.assertEqual( set( parsed[ 'nodes' ] ), set( neighborhood[ 'nodes' ] ) )
            
            graph_db.Close()
        
        finally:
            
            shutil.rmtree( graph_parent_dir, ignore_errors = True )



if __name__ == '__main__':
    
    unittest.main()
