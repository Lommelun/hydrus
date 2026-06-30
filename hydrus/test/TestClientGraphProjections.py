import os
import shutil
import tempfile
import unittest

from hydrus.client.graph import ClientGraphDB
from hydrus.client.graph import ClientGraphProjections
from hydrus.client.graph import ClientGraphSuggestions

from hydrus.test import ClientGraphTestFixtures
from hydrus.test import TestController

# Phase 2 check: CO_OCCURS + related-tag suggestions reproduce the grounding fixture's known,
# hand-designed ranking (TestClientGraphGrounding's own co-occurrence layout: cat shares 5 files
# with outdoors, 3 with play, 2 with dog, 0 with indoors -> outdoors > play > dog, indoors absent).
# This is the graph's own ground truth, not SQLite's related_tags output -- that's a different,
# sampled-approximation algorithm and asserting graph == SQLite would flake.

class TestClientGraphProjections( ClientGraphTestFixtures.GraphFixtureMixin, unittest.TestCase ):
    
    def test_cooccurrence_and_related_tags_match_grounding_ranking( self ):
        
        self._BuildFixture()
        
        # the projection reads SQLite directly (see ClientGraphProjections), so it needs the
        # fixture's writes actually committed to disk first, not just visible to Hydrus's own
        # in-process connection -- Hydrus batches commits, it doesn't commit per write
        type( self )._db.ForceACommit()
        
        graph_parent_dir = tempfile.mkdtemp( prefix = 'hydrus_graph_cooccur_' )
        graph_dir = os.path.join( graph_parent_dir, 'graph' )
        
        try:
            
            graph_db = ClientGraphDB.GraphDB( graph_dir )
            
            ClientGraphProjections.RebuildCoOccurrence( graph_db, TestController.DB_DIR, self.personal_key, min_count = 1 )
            
            related = ClientGraphSuggestions.GetRelatedTags( graph_db, 'cat', self.personal_key )
            ordered_values = [ tag for ( tag, count, weight ) in related ]
            
            self.assertIn( 'outdoors', ordered_values )
            self.assertIn( 'play', ordered_values )
            self.assertIn( 'dog', ordered_values )
            self.assertNotIn( 'indoors', ordered_values )  # zero overlap with cat
            
            self.assertLess( ordered_values.index( 'outdoors' ), ordered_values.index( 'play' ) )
            self.assertLess( ordered_values.index( 'play' ), ordered_values.index( 'dog' ) )
            
            graph_db.Close()
        
        finally:
            
            shutil.rmtree( graph_parent_dir, ignore_errors = True )



if __name__ == '__main__':
    
    unittest.main()
