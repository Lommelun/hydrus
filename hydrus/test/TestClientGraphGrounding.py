import os
import shutil
import tempfile
import time
import typing
import unittest

from PIL import Image

from hydrus.core import HydrusConstants as HC
from hydrus.core import HydrusData

from hydrus.client import ClientConstants as CC
from hydrus.client import ClientServices
from hydrus.client.db import ClientDB
from hydrus.client.importing import ClientImportFiles
from hydrus.client.importing.options import ImportOptionsConstants as IOC
from hydrus.client.importing.options import ImportOptionsManager
from hydrus.client.metadata import ClientContentUpdates
from hydrus.client.metadata import ClientTags
from hydrus.client.search import ClientSearchTagContext

from hydrus.test import TestController
from hydrus.test import TestGlobals as TG

# Grounding/characterization tests for the tag-graph plan: pin CURRENT sqlite behaviour
# (canonical/ideal resolution, cross-service sibling application-order precedence, ancestors,
# related-tag ranking) so a future graph backend has a concrete baseline to match.
#
# ponytail: reuses one shared fixture builder per test (small DB rebuild cost) instead of a
# class-level shared fixture, matching the existing TestClientDB*/TestClientDBTags style in this
# codebase rather than inventing a new harness pattern.

class TestClientGraphGrounding( unittest.TestCase ):

    _db: typing.Any = None

    @classmethod
    def _delete_db( cls ):

        cls._db.Shutdown()

        while not cls._db.LoopIsFinished():

            time.sleep( 0.1 )


        for filename in list( cls._db._db_filenames.values() ):

            os.remove( os.path.join( TestController.DB_DIR, filename ) )


        del cls._db

        TG.test_controller.ClearTestDB()


    @classmethod
    def setUpClass( cls ):

        cls._db = ClientDB.DB( TG.test_controller, TestController.DB_DIR, 'client' )

        TG.test_controller.SetTestDB( cls._db )


    @classmethod
    def tearDownClass( cls ):

        cls._delete_db()


    def _read( self, action, *args, **kwargs ): return TestClientGraphGrounding._db.Read( action, *args, **kwargs )
    def _write( self, action, *args, **kwargs ): return TestClientGraphGrounding._db.Write( action, True, *args, **kwargs )

    def _SyncDisplay( self, service_keys ):

        for service_key in service_keys:

            while self._write( 'sync_tag_display_maintenance', service_key, 1 ):

                pass




    def _ImportFile( self, path ):

        full_import_options_container = ImportOptionsManager.ImportOptionsManager.STATICGetDefaultInitialisedManager().GetDefaultImportOptionsContainerForCallerType( IOC.IMPORT_OPTIONS_CALLER_TYPE_GLOBAL )

        file_import_job = ClientImportFiles.FileImportJob( path, full_import_options_container )

        file_import_job.GeneratePreImportHashAndStatus()
        file_import_job.GenerateInfo()

        self._write( 'import_file', file_import_job )

        return file_import_job.GetHash()


    def _BuildFixture( self ):

        TestClientGraphGrounding._delete_db()
        TestClientGraphGrounding._db = ClientDB.DB( TG.test_controller, TestController.DB_DIR, 'client' )
        TG.test_controller.SetTestDB( TestClientGraphGrounding._db )

        services = list( self._read( 'services' ) )

        self.source_key = HydrusData.GenerateKey()
        self.ptr_key = HydrusData.GenerateKey()
        self.personal_key = CC.DEFAULT_LOCAL_TAG_SERVICE_KEY

        services.append( ClientServices.GenerateService( self.source_key, HC.LOCAL_TAG, 'safebooru' ) )
        services.append( ClientServices.GenerateService( self.ptr_key, HC.TAG_REPOSITORY, 'ptr (test)' ) )

        self._write( 'update_services', services )

        # 8 distinct generated files, real imports (so hashes are real and the fixture also works
        # for an actual client run, not just raw db pokes)
        tmp_dir = tempfile.mkdtemp( prefix = 'hydrus_graph_grounding_' )

        try:

            colours = [ (200,0,0),(0,200,0),(0,0,200),(200,200,0),(200,0,200),(0,200,200),(100,0,0),(0,100,0) ]
            hashes = []

            for ( i, rgb ) in enumerate( colours ):

                path = os.path.join( tmp_dir, f'f{i}.png' )

                Image.new( 'RGB', ( 64, 64 ), rgb ).save( path, 'PNG' )

                hashes.append( self._ImportFile( path ) )


        finally:

            shutil.rmtree( tmp_dir, ignore_errors = True )


        ( f1, f2, f3, f4, f5, f6, f7, f8 ) = hashes
        self.hashes = hashes

        # co-occurrence layout: cat={f1..f6}, outdoors={f1..f5} (5/6 overlap), play={f1,f3,f5,f7}
        # (3 overlap), dog={f5,f6,f7,f8} (2 overlap), indoors={f7,f8} (0 overlap) -> unambiguous
        # ranking outdoors > play > dog, indoors excluded
        tag_to_files = {
            'cat' : ( f1, f2, f3, f4, f5, f6 ),
            'outdoors' : ( f1, f2, f3, f4, f5 ),
            'play' : ( f1, f3, f5, f7 ),
            'dog' : ( f5, f6, f7, f8 ),
            'indoors' : ( f7, f8 ),
        }

        mapping_updates = [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_MAPPINGS, HC.CONTENT_UPDATE_ADD, ( tag, hs ) ) for ( tag, hs ) in tag_to_files.items() ]

        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.personal_key, mapping_updates ) )
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.source_key, [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_MAPPINGS, HC.CONTENT_UPDATE_ADD, ( 'kitty', ( f1, ) ) ) ] ) )
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.ptr_key, [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_MAPPINGS, HC.CONTENT_UPDATE_ADD, ( 'doggo', ( f6, ) ) ) ] ) )

        # siblings: source/ptr agree kitty/neko -> cat; ptr vs personal CONFLICT on doggo (puppy vs dog)
        # -> this is the cross-service application-order precedence case
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.personal_key, [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_ADD, ( 'doggo', 'dog' ) ) ] ) )
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.source_key, [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_ADD, ( 'kitty', 'cat' ) ) ] ) )
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.ptr_key, [
            ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_ADD, ( 'neko', 'cat' ) ),
            ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_ADD, ( 'doggo', 'puppy' ) ),
        ] ) )

        # parents: cat -> feline -> animal (personal); dog -> canine -> animal (ptr), shared root
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.personal_key, [
            ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_PARENTS, HC.CONTENT_UPDATE_ADD, ( 'cat', 'feline' ) ),
            ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_PARENTS, HC.CONTENT_UPDATE_ADD, ( 'feline', 'animal' ) ),
        ] ) )
        self._write( 'content_updates', ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( self.ptr_key, [
            ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_PARENTS, HC.CONTENT_UPDATE_ADD, ( 'dog', 'canine' ) ),
            ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_PARENTS, HC.CONTENT_UPDATE_ADD, ( 'canine', 'animal' ) ),
        ] ) )

        self._SyncDisplay( ( self.personal_key, self.source_key, self.ptr_key ) )


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
