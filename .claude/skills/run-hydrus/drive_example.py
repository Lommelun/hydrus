#!/usr/bin/env python3
"""
Drive the running hydrus client *in-process* via Qt -- type, click, and assert
widget state -- with NO display and NO OS permission. This is the template for
interactively exercising the app (e.g. to verify a PR's UI behaviour).

Why in-process instead of OS-level clicks: code runs inside the hydrus process,
so it injects synthetic Qt events (QTest) straight into the event loop and reads
widget state back (button.IsOn(), lineedit.text()). OS input (CGEvent/AppleScript)
would need a real window + Accessibility permission + pixel coordinates and can't
read state. The Qt path works under QT_QPA_PLATFORM=offscreen, so it runs in CI.

This example: types a predicate into the tag autocomplete (keyboard), then clicks
the "searching immediately" on/off toggle (mouse), asserting its state flips. It
screenshots each step. Adapt step0/step1/step2 to drive whatever you need:
find widgets with main.findChildren(<QtClass>) and match on
.metaObject().className() / .text(), then QTest.keyClicks / QTest.mouseClick /
QAction.trigger(), and read back hydrus's own state methods to assert.

Run via driver.sh:  bash .claude/skills/run-hydrus/driver.sh drive
Env: HYDRUS_DB (throwaway db), DRIVE_OUT (report file), DRIVE_SHOTS (png dir).
"""

import os
import sys
import time
import threading
from pathlib import Path

os.environ.setdefault( 'QT_QPA_PLATFORM', 'offscreen' )

DB = os.environ[ 'HYDRUS_DB' ]
OUT = os.environ.get( 'DRIVE_OUT', os.path.join( os.environ.get( 'DRIVE_SHOTS', '/tmp' ), 'drive.out' ) )
SHOTDIR = os.environ.get( 'DRIVE_SHOTS', '/tmp' )

# run from source: put the repo root (dir with hydrus_client.py) first on sys.path
_here = Path( __file__ ).resolve()
for _p in [ _here ] + list( _here.parents ):

    if ( _p / 'hydrus_client.py' ).exists():

        sys.path.insert( 0, str( _p ) )
        os.chdir( _p )
        break


sys.argv = [ 'hydrus_client.py', '-d', DB ]

from qtpy.QtWidgets import QApplication, QLineEdit, QAbstractButton
from qtpy.QtCore import QObject, Signal, Qt, QTimer
from qtpy.QtTest import QTest

_f = open( OUT, 'w' )
def L( *a ):
    _f.write( ' '.join( str( x ) for x in a ) + '\n' ); _f.flush()

def shot( w, name ):
    w.grab().save( os.path.join( SHOTDIR, name ) )
    L( '  shot ->', name, f'{w.width()}x{w.height()}' )


class Driver( QObject ):

    go = Signal()

    def __init__( self ):

        super().__init__()
        self.go.connect( self.step0, Qt.QueuedConnection )


    def _find( self ):

        tops = [ w for w in QApplication.topLevelWidgets() if w.isVisible() ]
        self.main = max( tops, key = lambda w: w.width() * w.height() )
        self.le = next( w for w in self.main.findChildren( QLineEdit ) if w.isVisible() )
        self.toggle = next(
            b for b in self.main.findChildren( QAbstractButton )
            if b.metaObject().className() == 'OnOffButton' and 'searching' in b.text().lower()
        )


    def step0( self ):

        self._find()
        L( 'window:', self.main.metaObject().className(), repr( self.main.windowTitle() ) )
        L( 'toggle:', repr( self.toggle.text() ), 'IsOn=', self.toggle.IsOn() )
        shot( self.main, 'drive_0_idle.png' )

        # KEYBOARD: synthetic key events into the tag autocomplete
        self.le.setFocus()
        QTest.keyClicks( self.le, 'system:inbox' )
        L( 'typed "system:inbox" via QTest.keyClicks' )
        QTimer.singleShot( 2500, self.step1 )   # let the async DB autocomplete respond


    def step1( self ):

        L( 'autocomplete reads:', repr( self.le.text() ) )
        shot( self.main, 'drive_1_typed.png' )

        # MOUSE: synthetic click on the on/off toggle
        self.before = self.toggle.IsOn()
        QTest.mouseClick( self.toggle, Qt.LeftButton )
        L( f'clicked toggle (was IsOn={self.before}); label now {self.toggle.text()!r}' )
        QTimer.singleShot( 800, self.step2 )


    def step2( self ):

        after = self.toggle.IsOn()
        shot( self.main, 'drive_2_clicked.png' )

        keyboard_ok = self.le.text() == 'system:inbox'
        click_ok = self.before != after
        L( f'ASSERT keyboard landed: {keyboard_ok}' )
        L( f'ASSERT click flipped toggle: {click_ok} ({self.before} -> {after})' )
        L( 'RESULT', 'PASS' if ( keyboard_ok and click_ok ) else 'FAIL' )
        os._exit( 0 if ( keyboard_ok and click_ok ) else 5 )


driver = Driver()

def worker():

    while QApplication.instance() is None:

        time.sleep( 0.3 )


    time.sleep( float( os.environ.get( 'DRIVE_DELAY', '20' ) ) )
    driver.go.emit()


threading.Thread( target = worker, daemon = True ).start()

from hydrus import hydrus_client_boot

hydrus_client_boot.boot()
