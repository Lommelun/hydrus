import os
import threading

from hydrus.client.graph import ClientGraphDB
from hydrus.client.graph import ClientGraphMigrate
from hydrus.client.graph import ClientGraphSync

# Only constructed when 'enable_tag_graph' is on (see ClientController.py) -- ladybug is never
# imported otherwise.

class GraphController( object ):
    
    def __init__( self, controller ):
        
        self._controller = controller
        self._import_lock = threading.Lock()  # Shutdown must not close the db under a running import
        self.import_finished = threading.Event()  # lets callers (tests, a future GUI) wait on the bootstrap import
        
        graph_dir = os.path.join( controller.db_dir, 'graph' )
        
        self.graph_db = ClientGraphDB.GraphDB( graph_dir )
        
        sync = ClientGraphSync.GraphSync( self.graph_db )
        
        self._controller.sub( sync, 'ProcessContentUpdatePackage', 'content_updates_gui' )
        
        if self.graph_db.IsEmpty():
            
            # first boot with the option on: bootstrap from whatever SQLite already has. Off the
            # boot thread since this walks every tag service and can take a while on a real db.
            self._controller.CallToThreadLongRunning( self.Import )
        
        else:
            
            self.import_finished.set()
    
    
    
    def Import( self ):
        
        self.import_finished.clear()
        
        try:
            
            with self._import_lock:
                
                ClientGraphMigrate.ImportFromHydrusDB( self.graph_db, self._controller )
        
        
        finally:
            
            self.import_finished.set()
    
    
    
    def Shutdown( self ):
        
        with self._import_lock:
            
            self.graph_db.Close()


