import os
import shutil
import tempfile
import time
import typing

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

from hydrus.test import TestController
from hydrus.test import TestGlobals as TG

# Shared scratch-db + fixture builder for the tag-graph plan's tests. Not a unittest.TestCase
# itself (mixin only) -- loadTestsFromModule picks up TestCase subclasses by name even when merely
# imported, so a reusable TestCase here would get re-run by every module that imports it.

class GraphFixtureMixin( object ):
    
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
    
    
    def _read( self, action, *args, **kwargs ): return type( self )._db.Read( action, *args, **kwargs )
    def _write( self, action, *args, **kwargs ): return type( self )._db.Write( action, True, *args, **kwargs )
    
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
        
        type( self )._delete_db()
        type( self )._db = ClientDB.DB( TG.test_controller, TestController.DB_DIR, 'client' )
        TG.test_controller.SetTestDB( type( self )._db )
        
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

