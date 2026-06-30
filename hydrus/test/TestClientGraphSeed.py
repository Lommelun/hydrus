import hashlib
import json
import os
import tempfile
import time
import unittest
import urllib.request

from hydrus.core import HydrusConstants as HC
from hydrus.core import HydrusData

from hydrus.client import ClientServices
from hydrus.client.db import ClientDB
from hydrus.client.metadata import ClientContentUpdates

from hydrus.test import TestGlobals as TG

# Not a real test: a one-off seeder for the graph-plan benchmark corpus. Its own module/suite
# ('client_graph_seed') so it never gets pulled into a normal 'client_graph' run (unittest's
# loadTestsFromModule loads everything in a module, so this can't share a file with the fast
# deterministic tests without silently dragging a slow network fetch into every run). Run with:
#   QT_QPA_PLATFORM=offscreen ./venv/bin/python hydrus_test.py client_graph_seed
#
# ponytail: one local tag service for all sample tags, not the personal/ptr/source split -- that
# precedence mechanic is already proven by TestClientGraphGrounding. This corpus exists for
# realistic co-occurrence + benchmarking, not to re-prove the application-order mechanic.
#
# ponytail: no real image downloads / import_file. Tried that first -- it routes physical file
# storage through TG.test_controller's OWN ephemeral client_files_manager (rooted at its own
# tempfile.mkdtemp(), unrelated to our target db dir), not something a second ClientDB.DB instance
# can redirect. Root cause: the graph plan's File node is hash-identity-only (no file bytes), and
# GetHashId() is get-or-create just like GetTagId(), so mapping writes need no prior import_file at
# all -- a stable synthetic hash per post is enough. Real bytes only matter for actually browsing
# the corpus in the GUI later; add a real import pass then if wanted.
SAFEBOORU_SEED_TARGET_POSTS = int( os.environ.get( 'HYDRUS_GRAPH_SEED_POSTS', '3000' ) )
SAFEBOORU_SEED_DB_DIR = os.environ.get( 'HYDRUS_GRAPH_SEED_DB_DIR', os.path.join( tempfile.gettempdir(), 'hydrus_graph_seed_db' ) )

class TestSeedSafebooruSample( unittest.TestCase ):

    def test_seed( self ):

        os.makedirs( SAFEBOORU_SEED_DB_DIR, exist_ok = True )

        db = ClientDB.DB( TG.test_controller, SAFEBOORU_SEED_DB_DIR, 'client' )
        TG.test_controller.SetTestDB( db )

        try:

            services = list( db.Read( 'services' ) )

            existing = next( ( s for s in services if s.GetName() == 'safebooru' ), None )

            if existing is None:

                source_key = HydrusData.GenerateKey()

                services.append( ClientServices.GenerateService( source_key, HC.LOCAL_TAG, 'safebooru' ) )

                db.Write( 'update_services', True, services )

            else:

                source_key = existing.GetServiceKey()


            imported = 0
            pid = 0

            while imported < SAFEBOORU_SEED_TARGET_POSTS:

                url = f'https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1&limit=100&pid={pid}'

                try:

                    with urllib.request.urlopen( url, timeout = 15 ) as resp:

                        posts = json.loads( resp.read() )


                except Exception as e:

                    print( f'page fetch failed, stopping: {e}' )

                    break


                if not posts:

                    break  # ran out of posts


                content_updates = []

                for post in posts:

                    tags = post.get( 'tags', '' ).split()
                    post_id = post.get( 'id' )

                    if not tags or post_id is None:

                        continue


                    file_hash = hashlib.sha256( f'safebooru:{post_id}'.encode( 'utf8' ) ).digest()

                    content_updates.extend( ClientContentUpdates.ContentUpdate( HC.CONTENT_TYPE_MAPPINGS, HC.CONTENT_UPDATE_ADD, ( tag, ( file_hash, ) ) ) for tag in tags )

                    imported += 1

                    if imported >= SAFEBOORU_SEED_TARGET_POSTS:

                        break



                if content_updates:

                    db.Write( 'content_updates', True, ClientContentUpdates.ContentUpdatePackage.STATICCreateFromContentUpdates( source_key, content_updates ) )


                print( f'imported {imported}/{SAFEBOORU_SEED_TARGET_POSTS}' )

                pid += 1

                time.sleep( 0.3 )


            print( f'done: {imported} posts seeded into {SAFEBOORU_SEED_DB_DIR}' )

        finally:

            db.Shutdown()

            while not db.LoopIsFinished():

                time.sleep( 0.1 )


            TG.test_controller.ClearTestDB()


if __name__ == '__main__':

    unittest.main()
