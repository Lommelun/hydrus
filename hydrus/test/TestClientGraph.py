import os
import shutil
import tempfile
import unittest

from hydrus.core import HydrusConstants as HC
from hydrus.core import HydrusData

from hydrus.client.graph import ClientGraphController
from hydrus.client.graph import ClientGraphDB
from hydrus.client.graph import ClientGraphMigrate
from hydrus.client.graph import ClientGraphSync
from hydrus.client.metadata import ClientContentUpdates
from hydrus.client.metadata import ClientTags

from hydrus.test import ClientGraphTestFixtures
from hydrus.test import TestGlobals as TG

# Phase 1 parity check: the one-time importer should reproduce, exactly, what SQLite already
# computed for the same fixture TestClientGraphGrounding asserts against -- not a fresh
# specification, a mirror.

class TestClientGraphMigration( ClientGraphTestFixtures.GraphFixtureMixin, unittest.TestCase ):
    
    def test_importer_matches_sqlite_ideals_and_ancestors( self ):
        
        self._BuildFixture()
        
        graph_parent_dir = tempfile.mkdtemp( prefix = 'hydrus_graph_migrate_' )
        graph_dir = os.path.join( graph_parent_dir, 'graph' )  # ladybug creates this itself, must not pre-exist
        
        try:
            
            graph_db = ClientGraphDB.GraphDB( graph_dir )
            
            ClientGraphMigrate.ImportFromHydrusDB( graph_db, type( self )._db )
            
            for service_key in ( self.personal_key, self.source_key, self.ptr_key ):
                
                sqlite_ideals = self._read( 'tag_siblings_all_ideals', service_key )
                
                for ( bad_tag, expected_ideal ) in sqlite_ideals.items():
                    
                    self.assertEqual( graph_db.GetIdeal( bad_tag, service_key ), expected_ideal )
            
            
            result = self._read( 'tag_siblings_and_parents_lookup', ClientTags.TAG_DISPLAY_DISPLAY_ACTUAL, ( 'cat', 'dog' ) )
            
            ( _, _, _, cat_ancestors ) = result[ 'cat' ][ self.personal_key ]
            ( _, _, _, dog_ancestors ) = result[ 'dog' ][ self.ptr_key ]
            
            self.assertEqual( graph_db.GetAncestors( 'cat', self.personal_key ), cat_ancestors )
            self.assertEqual( graph_db.GetAncestors( 'dog', self.ptr_key ), dog_ancestors )
            
            graph_db.Close()

        finally:

            shutil.rmtree( graph_parent_dir, ignore_errors = True )


    def test_importer_matches_sqlite_ancestors_under_cross_service_application_order( self ):

        # the discriminating case: personal's own chain (cat->feline->animal) is fine to mirror
        # per-service, but 'dog' has no parent rule on personal at all -- only PTR does
        # (dog->canine->animal). Once personal's applicable-parent-services order includes PTR,
        # SQLite unions that rule into personal's own display; the importer has to match it, not
        # just personal's own raw tag_parents pairs.

        self._BuildFixture()

        order = { self.personal_key : [ self.personal_key, self.ptr_key, self.source_key ] }
        self._write( 'tag_display_application', order, order )
        self._SyncDisplay( ( self.personal_key, ) )

        graph_parent_dir = tempfile.mkdtemp( prefix = 'hydrus_graph_migrate_cross_' )
        graph_dir = os.path.join( graph_parent_dir, 'graph' )

        try:

            graph_db = ClientGraphDB.GraphDB( graph_dir )

            ClientGraphMigrate.ImportFromHydrusDB( graph_db, type( self )._db )

            result = self._read( 'tag_siblings_and_parents_lookup', ClientTags.TAG_DISPLAY_DISPLAY_ACTUAL, ( 'dog', ) )

            ( _, _, _, expected_ancestors ) = result[ 'dog' ][ self.personal_key ]

            self.assertEqual( expected_ancestors, { 'canine', 'animal' } )  # sanity: cross-service application is actually in effect
            self.assertEqual( graph_db.GetAncestors( 'dog', self.personal_key ), expected_ancestors )

            graph_db.Close()

        finally:

            shutil.rmtree( graph_parent_dir, ignore_errors = True )



class TestClientGraphControllerWiring( ClientGraphTestFixtures.GraphFixtureMixin, unittest.TestCase ):
    
    def test_construct_auto_imports( self ):
        
        # ponytail: doesn't also assert live content_updates_gui delivery here -- TG.test_controller's
        # 'pub' is a deliberate no-op in this headless test harness (only 'pubimmediate' dispatches),
        # so there is nothing to deliver to outside the real app. The subscription call itself uses
        # the same controller.sub(...) pattern as every other manager in the codebase, and
        # GraphSync.ProcessContentUpdatePackage's actual translation logic has its own direct test
        # below that doesn't depend on pubsub at all.
        
        self._BuildFixture()
        
        controller = ClientGraphController.GraphController( TG.test_controller )
        
        try:
            
            # graph starts empty -> auto-import runs on a background thread (CallToThreadLongRunning)
            finished = controller.import_finished.wait( timeout = 10 )
            self.assertTrue( finished )
            
            self.assertFalse( controller.graph_db.IsEmpty() )
            self.assertEqual( controller.graph_db.GetIdeal( 'kitty', self.source_key ), 'cat' )
        
        finally:
            
            controller.Shutdown()



class TestClientGraphSync( unittest.TestCase ):
    
    def test_process_content_update_package_add_and_delete( self ):
        
        graph_parent_dir = tempfile.mkdtemp( prefix = 'hydrus_graph_sync_' )
        graph_dir = os.path.join( graph_parent_dir, 'graph' )
        
        try:
            
            graph_db = ClientGraphDB.GraphDB( graph_dir )
            sync = ClientGraphSync.GraphSync( graph_db )
            
            service_key = HydrusData.GenerateKey()
            
            add_package = ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( service_key, [
                ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_ADD, ( 'kitty', 'cat' ) ),
            ] )
            
            sync.ProcessContentUpdatePackage( add_package )
            
            self.assertEqual( graph_db.GetIdeal( 'kitty', service_key ), 'kitty' )  # IDEAL_OF isn't live-synced, only the raw edge is
            
            result = graph_db.Execute( 'MATCH (a:Tag {tag: $a})-[:SIBLING_OF {service_key: $sk}]->(b:Tag {tag: $b}) RETURN count(*)', { 'a' : 'kitty', 'b' : 'cat', 'sk' : service_key.hex() } )
            self.assertEqual( result.get_next()[ 0 ], 1 )
            
            delete_package = ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( service_key, [
                ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_DELETE, ( 'kitty', 'cat' ) ),
            ] )
            
            sync.ProcessContentUpdatePackage( delete_package )
            
            result = graph_db.Execute( 'MATCH (a:Tag {tag: $a})-[:SIBLING_OF {service_key: $sk}]->(b:Tag {tag: $b}) RETURN count(*)', { 'a' : 'kitty', 'b' : 'cat', 'sk' : service_key.hex() } )
            self.assertEqual( result.get_next()[ 0 ], 0 )
            
            graph_db.Close()
        
        finally:
            
            shutil.rmtree( graph_parent_dir, ignore_errors = True )



if __name__ == '__main__':
    
    unittest.main()
