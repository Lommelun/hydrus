import json
import os
import tempfile
import time
import unittest

from hydrus.core import HydrusConstants as HC
from hydrus.core import HydrusSerialisable
from hydrus.core.files import HydrusFilesPhysicalStorage

from hydrus.client import ClientAPI
from hydrus.client import ClientConstants as CC
from hydrus.client import ClientServices
from hydrus.client.db import ClientDB
from hydrus.client.metadata import ClientContentUpdates

from hydrus.test import TestGlobals as TG

# Not a real test: a one-off seeder for dev_run_with_sample.py (repo root), which boots the real
# GUI against a throwaway db so you can interactively explore the tag-graph feature with real
# data. Temporary, for developing hydrus/client/graph/ -- delete both once that feature ships.
#
# ponytail: siblings/parents come from a precomputed JSON (real danbooru tag_aliases/
# tag_implications for our safebooru sample's actual tag vocabulary), not a live PTR sync --
# a full PTR sync takes weeks, and danbooru's alias/implication data is what the PTR itself is
# largely sourced from, so it's a real, representative stand-in for "source -> PTR -> personal"
# precedence, not synthetic test fixture data.
#
# ponytail: doesn't seed file mappings here. dev_run_with_sample.py adds real files + their real
# tags afterward via the Client API (add_files/add_tags), which runs through the live client's
# own file manager -- the direct-DB route hit real client_files routing problems (see TestClientGraph
# session history); the API is also just the documented, correct way external tools add files.

SEED_DB_DIR = os.environ.get( 'HYDRUS_GRAPH_DEV_DB_DIR', os.path.join( tempfile.gettempdir(), 'hydrus_dev_sample_db' ) )
RELATIONS_JSON = os.environ.get( 'HYDRUS_GRAPH_DEV_RELATIONS_JSON', os.path.join( os.path.dirname( __file__ ), '..', '..', 'dev_sample_tag_relations.json' ) )
API_PORT = int( os.environ.get( 'HYDRUS_GRAPH_DEV_API_PORT', '45869' ) )
API_ACCESS_KEY_HEX = os.environ.get( 'HYDRUS_GRAPH_DEV_API_KEY', '2fe9519d69f505698cce86b24fa1cfbd5555c082e268cc4a4303150e81eba473' )

SOURCE_TAG_SERVICE_KEY = b'safebooru (dev demo)'
PTR_TAG_SERVICE_KEY = b'ptr (dev demo)'

class TestDevDemoSeed( unittest.TestCase ):
    
    def test_seed( self ):
        
        os.makedirs( SEED_DB_DIR, exist_ok = True )
        
        # the real GUI's ClientFilesManager treats a registered-but-absent client_files
        # subfolder as a drive-went-missing emergency (it prompts for confirmation rather than
        # just creating it) once the db has its own location rows -- which it will, the moment
        # ClientDB.DB below runs its fresh-db default-services setup. Pre-create the full f00-fff
        # / t00-tff layout now so there is nothing "missing" by the time the real client boots.
        client_files_dir = os.path.join( SEED_DB_DIR, 'client_files' )
        
        for prefix_type in ( 'f', 't' ):
            
            for prefix in HydrusFilesPhysicalStorage.IteratePrefixes( prefix_type, HydrusFilesPhysicalStorage.DEFAULT_PREFIX_LENGTH ):
                
                os.makedirs( os.path.join( client_files_dir, prefix ), exist_ok = True )
        
        db = ClientDB.DB( TG.test_controller, SEED_DB_DIR, 'client' )
        TG.test_controller.SetTestDB( db )
        
        try:
            
            services = list( db.Read( 'services' ) )
            
            if not any( s.GetServiceKey() == SOURCE_TAG_SERVICE_KEY for s in services ):
                
                services.append( ClientServices.GenerateService( SOURCE_TAG_SERVICE_KEY, HC.LOCAL_TAG, 'safebooru' ) )
            
            
            if not any( s.GetServiceKey() == PTR_TAG_SERVICE_KEY for s in services ):
                
                services.append( ClientServices.GenerateService( PTR_TAG_SERVICE_KEY, HC.LOCAL_TAG, 'PTR (sample)' ) )
            
            
            services = [ s for s in services if s.GetServiceKey() != CC.CLIENT_API_SERVICE_KEY ]
            
            client_api_dictionary = ClientServices.GenerateDefaultServiceDictionary( HC.CLIENT_API_SERVICE )
            client_api_dictionary[ 'port' ] = API_PORT
            
            services.append( ClientServices.GenerateService( CC.CLIENT_API_SERVICE_KEY, HC.CLIENT_API_SERVICE, 'client api', client_api_dictionary ) )
            
            db.Write( 'update_services', True, services )
            
            client_api_manager = db.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_CLIENT_API_MANAGER )
            
            if client_api_manager is None:
                
                client_api_manager = ClientAPI.APIManager()
            
            
            permissions = ClientAPI.APIPermissions( name = 'dev demo', access_key = bytes.fromhex( API_ACCESS_KEY_HEX ), permits_everything = True )
            
            client_api_manager.AddAccess( permissions )
            
            db.Write( 'serialisable', True, client_api_manager )
            
            new_options = db.Read( 'serialisable', HydrusSerialisable.SERIALISABLE_TYPE_CLIENT_OPTIONS )
            
            new_options.SetBoolean( 'enable_tag_graph', True )
            
            db.Write( 'serialisable', True, new_options )
            
            with open( RELATIONS_JSON ) as f:
                
                relations = json.load( f )
            
            
            sibling_updates = [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_SIBLINGS, HC.CONTENT_UPDATE_ADD, ( bad, good ) ) for ( bad, good ) in relations[ 'siblings' ] ]
            parent_updates = [ ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_TAG_PARENTS, HC.CONTENT_UPDATE_ADD, ( child, parent ) ) for ( child, parent ) in relations[ 'parents' ] ]
            
            db.Write( 'content_updates', True, ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( PTR_TAG_SERVICE_KEY, sibling_updates + parent_updates ) )
            
            while db.Write( 'sync_tag_display_maintenance', True, PTR_TAG_SERVICE_KEY, 1 ):
                
                pass
            
            
            print( f'seeded {SEED_DB_DIR}: client api on port {API_PORT}, {len(relations["siblings"])} siblings + {len(relations["parents"])} parents on PTR (sample)' )
        
        finally:
            
            db.Shutdown()
            
            while not db.LoopIsFinished():
                
                time.sleep( 0.1 )
            
            
            TG.test_controller.ClearTestDB()



if __name__ == '__main__':
    
    unittest.main()
