import unittest

from hydrus.client import ClientConstants as CC
from hydrus.client.metadata import ClientTags
from hydrus.client.search import ClientSearchTagContext

from hydrus.test import ClientGraphTestFixtures

# Grounding/characterization tests for the tag-graph plan: pin CURRENT sqlite behaviour
# (canonical/ideal resolution, cross-service sibling application-order precedence, ancestors,
# related-tag ranking) so a future graph backend has a concrete baseline to match.

class TestClientGraphGrounding( ClientGraphTestFixtures.GraphFixtureMixin, unittest.TestCase ):
    
    def test_ancestors_per_service( self ):
        
        self._BuildFixture()
        
        result = self._read( 'tag_siblings_and_parents_lookup', ClientTags.TAG_DISPLAY_DISPLAY_ACTUAL, ( 'cat', 'dog' ) )
        
        ( _, ideal, _, ancestors ) = result[ 'cat' ][ self.personal_key ]
        self.assertEqual( ideal, 'cat' )
        self.assertEqual( ancestors, { 'feline', 'animal' } )
        
        ( _, ideal, _, ancestors ) = result[ 'dog' ][ self.ptr_key ]
        self.assertEqual( ideal, 'dog' )
        self.assertEqual( ancestors, { 'canine', 'animal' } )
    
    
    def test_application_order_precedence( self ):
        
        # this is THE thing to nail down for the graph plan: a contested bad_tag ('doggo') is won
        # by whichever applicable service comes FIRST in the configured order (first-definer-wins,
        # not last-wins) -- confirmed empirically here since no existing hydrus test covers
        # tag_display_application/SetApplication at all (the stubs in TestClientDBTags are all
        # `pass`).
        
        self._BuildFixture()
        
        # ponytail: master = personal_key, not CC.COMBINED_TAG_SERVICE_KEY ('all known tags').
        # The synthetic combined service never gets its sibling cache tables created by vanilla
        # hydrus's update_services path (only "real" tag services do) -- that's an upstream gap,
        # not ours to fix here. A real service as master proves the identical precedence mechanic.
        
        order = { self.personal_key : [ self.personal_key, self.ptr_key, self.source_key ] }
        self._write( 'tag_display_application', order, order )
        self._SyncDisplay( ( self.personal_key, ) )
        
        ideals = self._read( 'tag_siblings_all_ideals', self.personal_key )
        self.assertEqual( ideals[ 'doggo' ], 'dog' )  # personal is first -> personal wins
        self.assertEqual( ideals[ 'kitty' ], 'cat' )
        self.assertEqual( ideals[ 'neko' ], 'cat' )
        
        order = { self.personal_key : [ self.source_key, self.ptr_key, self.personal_key ] }
        self._write( 'tag_display_application', order, order )
        self._SyncDisplay( ( self.personal_key, ) )
        
        ideals = self._read( 'tag_siblings_all_ideals', self.personal_key )
        self.assertEqual( ideals[ 'doggo' ], 'puppy' )  # source has no 'doggo' rule -> ptr (next) wins
    
    
    def test_related_tags_ranking( self ):
        
        self._BuildFixture()
        
        tag_context = ClientSearchTagContext.TagContext( service_key = self.personal_key )
        
        ( _num_searched, _num_to_search, _num_skipped, predicates ) = self._read( 'related_tags', CC.COMBINED_FILE_SERVICE_KEY, tag_context, { 'cat' } )
        
        ordered_values = [ pred.GetValue() for pred in predicates ]
        
        self.assertIn( 'outdoors', ordered_values )
        self.assertIn( 'play', ordered_values )
        self.assertIn( 'dog', ordered_values )
        self.assertNotIn( 'indoors', ordered_values )  # zero overlap
        
        self.assertLess( ordered_values.index( 'outdoors' ), ordered_values.index( 'play' ) )
        self.assertLess( ordered_values.index( 'play' ), ordered_values.index( 'dog' ) )


if __name__ == '__main__':
    
    unittest.main()
