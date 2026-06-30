#!/usr/bin/env python3
"""
Dev convenience for the hydrus/client/graph/ tag-graph feature: boots Hydrus against a throwaway
sample db, auto-populates it with real safebooru files + tags and real danbooru-sourced tag
sibling/parent relationships (a PTR-style stand-in -- a full PTR sync takes weeks, see
dev_sample_tag_relations.json), and deletes the throwaway db when you quit.

Temporary, for developing the tag-graph feature -- remove this script (and TestClientGraphDevDemoSeed.py,
dev_sample_tag_relations.json) once that feature ships.

Usage:
    python3 dev_run_with_sample.py [num_files]

Ctrl-C, or just close the Hydrus window, to quit and clean up.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

REPO_ROOT = os.path.dirname( os.path.abspath( __file__ ) )
PYTHON = os.path.join( REPO_ROOT, 'venv', 'bin', 'python' )

SAMPLE_DB_DIR = os.path.join( tempfile.gettempdir(), 'hydrus_dev_sample_db' )
RELATIONS_JSON = os.path.join( REPO_ROOT, 'dev_sample_tag_relations.json' )
API_PORT = 45869
API_ACCESS_KEY = '2fe9519d69f505698cce86b24fa1cfbd5555c082e268cc4a4303150e81eba473'
SOURCE_TAG_SERVICE_KEY_HEX = b'safebooru (dev demo)'.hex()

NUM_FILES = int( sys.argv[ 1 ] ) if len( sys.argv ) > 1 else 150
ALLOWED_EXT = ( '.jpg', '.jpeg', '.png', '.gif' )

client_process = None

def cleanup():
    
    global client_process
    
    if client_process is not None and client_process.poll() is None:
        
        print( '\nstopping client...' )
        client_process.terminate()
        
        try:
            
            client_process.wait( timeout = 15 )
        
        except subprocess.TimeoutExpired:
            
            client_process.kill()
    
    
    print( 'cleaning up throwaway sample db...' )
    shutil.rmtree( SAMPLE_DB_DIR, ignore_errors = True )


def handle_signal( signum, frame ):
    
    cleanup()
    sys.exit( 0 )


def seed_db():
    
    print( 'seeding sample db (services, client api, real tag siblings/parents)...' )
    
    env = dict( os.environ )
    env[ 'QT_QPA_PLATFORM' ] = 'offscreen'
    env[ 'HYDRUS_GRAPH_DEV_DB_DIR' ] = SAMPLE_DB_DIR
    env[ 'HYDRUS_GRAPH_DEV_RELATIONS_JSON' ] = RELATIONS_JSON
    env[ 'HYDRUS_GRAPH_DEV_API_PORT' ] = str( API_PORT )
    env[ 'HYDRUS_GRAPH_DEV_API_KEY' ] = API_ACCESS_KEY
    
    subprocess.run( [ PYTHON, 'hydrus_test.py', 'client_graph_dev_demo_seed' ], cwd = REPO_ROOT, env = env, check = True )


def boot_client():
    
    global client_process
    
    print( 'booting client...' )
    client_process = subprocess.Popen( [ PYTHON, 'hydrus_client.py', '-d', SAMPLE_DB_DIR ], cwd = REPO_ROOT )


def wait_for_api( timeout = 60 ):
    
    deadline = time.time() + timeout
    url = f'http://127.0.0.1:{API_PORT}/api_version'
    
    while time.time() < deadline:
        
        try:
            
            urllib.request.urlopen( url, timeout = 2 )
            return
        
        except Exception:
            
            time.sleep( 1 )
    
    
    raise RuntimeError( 'client api never came up' )


def api_post( path, payload ):
    
    req = urllib.request.Request(
        f'http://127.0.0.1:{API_PORT}{path}',
        data = json.dumps( payload ).encode( 'utf8' ),
        headers = { 'Content-Type' : 'application/json', 'Hydrus-Client-API-Access-Key' : API_ACCESS_KEY },
        method = 'POST',
    )
    
    with urllib.request.urlopen( req, timeout = 30 ) as resp:
        
        body = resp.read()
        
        return json.loads( body ) if body else {}


def import_sample_files():
    
    print( f'fetching {NUM_FILES} real safebooru posts...' )
    
    tmp_dir = tempfile.mkdtemp( prefix = 'hydrus_dev_sample_files_' )
    
    imported = 0
    pid = 0
    
    try:
        
        while imported < NUM_FILES:
            
            url = f'https://safebooru.org/index.php?page=dapi&s=post&q=index&json=1&limit=100&pid={pid}'
            
            with urllib.request.urlopen( url, timeout = 15 ) as resp:
                
                posts = json.loads( resp.read() )
            
            
            if not posts:
                
                break
            
            
            for post in posts:
                
                if imported >= NUM_FILES:
                    
                    break
                
                
                file_url = post.get( 'file_url', '' )
                tags = post.get( 'tags', '' ).split()
                ext = os.path.splitext( file_url )[ 1 ].lower()
                
                if not file_url or not tags or ext not in ALLOWED_EXT:
                    
                    continue
                
                
                local_path = os.path.join( tmp_dir, f"{post['id']}{ext}" )
                
                try:
                    
                    req = urllib.request.Request( file_url, headers = { 'User-Agent' : 'Mozilla/5.0' } )
                    
                    with urllib.request.urlopen( req, timeout = 15 ) as img_resp:
                        
                        with open( local_path, 'wb' ) as f:
                            
                            f.write( img_resp.read() )
                
                
                except Exception as e:
                    
                    print( f'  skip {post["id"]}: {e}' )
                    continue
                
                
                result = api_post( '/add_files/add_file', { 'path' : local_path } )
                file_hash = result.get( 'hash' )
                
                if file_hash:
                    
                    api_post( '/add_tags/add_tags', { 'hash' : file_hash, 'service_keys_to_tags' : { SOURCE_TAG_SERVICE_KEY_HEX : tags } } )
                    imported += 1
            
            
            
            print( f'  imported {imported}/{NUM_FILES}' )
            pid += 1
            time.sleep( 0.2 )
    
    
    finally:
        
        shutil.rmtree( tmp_dir, ignore_errors = True )
    
    
    print( f'done: {imported} real files imported with real tags' )


def main():
    
    signal.signal( signal.SIGINT, handle_signal )
    signal.signal( signal.SIGTERM, handle_signal )
    
    shutil.rmtree( SAMPLE_DB_DIR, ignore_errors = True )
    
    try:
        
        seed_db()
        boot_client()
        wait_for_api()
        import_sample_files()
        
        print( '\nsample data ready. Hydrus is running -- close its window or Ctrl-C here to quit and clean up.' )
        
        client_process.wait()
    
    finally:
        
        cleanup()



if __name__ == '__main__':
    
    main()
