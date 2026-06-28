#!/usr/bin/env python3
"""
Boot the real hydrus client and screenshot its main window from *inside* the
process, using Qt's QWidget.grab(). This renders the widget to a pixmap
directly, so it needs NO display and NO macOS Screen-Recording permission --
it works headless / offscreen / in CI, where `screencapture` and Quartz both
fail.

Run it via run-hydrus's driver.sh (which sets the venv + env), e.g.:

    HYDRUS_DB=/tmp/hydb HYDRUS_SHOT=/tmp/shot.png QT_QPA_PLATFORM=offscreen \
        venv/bin/python .claude/skills/run-hydrus/screenshot.py

Env:
  HYDRUS_DB         throwaway db dir to boot against (required)
  HYDRUS_SHOT       output PNG path (required)
  HYDRUS_SHOT_DELAY seconds to let the GUI build before grabbing (default 22)
"""

import os
import sys
import time
import threading
from pathlib import Path

# offscreen by default so this never touches a real display
os.environ.setdefault( 'QT_QPA_PLATFORM', 'offscreen' )

# Run from source: make sure the repo's hydrus package wins over any installed
# copy. A script puts ITS OWN dir on sys.path[0], not the cwd, so we find the
# repo root (the dir holding hydrus_client.py) and put it first.
_here = Path( __file__ ).resolve()
for _p in [ _here ] + list( _here.parents ):

    if ( _p / 'hydrus_client.py' ).exists():

        sys.path.insert( 0, str( _p ) )
        os.chdir( _p )
        break

DB = os.environ[ 'HYDRUS_DB' ]
OUT = os.environ[ 'HYDRUS_SHOT' ]
DELAY = float( os.environ.get( 'HYDRUS_SHOT_DELAY', '22' ) )

# hydrus_client_boot parses sys.argv at import time, so set it up first
sys.argv = [ 'hydrus_client.py', '-d', DB ]

from qtpy.QtWidgets import QApplication
from qtpy.QtCore import QObject, Signal, Qt

class Grabber( QObject ):

    go = Signal()

    def __init__( self ):

        super().__init__()

        # queued so the emit from the worker thread runs do() on the GUI thread
        self.go.connect( self.do, Qt.QueuedConnection )


    def do( self ):

        wins = [
            w for w in QApplication.topLevelWidgets()
            if w.isWindow() and w.isVisible() and w.width() > 200 and w.height() > 200
        ]

        # biggest visible top-level == the main client window (beats popups/splash)
        wins.sort( key = lambda w: w.width() * w.height(), reverse = True )

        if wins:

            target = wins[ 0 ]
            ok = target.grab().save( OUT )
            sys.stderr.write( f'GRAB {"ok" if ok else "FAILED"} -> {OUT}  {target.width()}x{target.height()}  title={target.windowTitle()!r}\n' )
            sys.stderr.flush()
            os._exit( 0 if ok else 3 )


        sys.stderr.write( 'GRAB: no visible top-level window yet\n' )
        sys.stderr.flush()
        os._exit( 4 )


grabber = Grabber()

def worker():

    # wait for the QApplication that hydrus creates during boot
    while QApplication.instance() is None:

        time.sleep( 0.3 )


    # let the gui finish constructing pages/managers
    time.sleep( DELAY )

    grabber.go.emit()


threading.Thread( target = worker, daemon = True ).start()

from hydrus import hydrus_client_boot

hydrus_client_boot.boot()
