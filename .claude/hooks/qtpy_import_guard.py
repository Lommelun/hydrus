#!/usr/bin/env python3
"""
Claude Code PreToolUse guard: block edits that introduce a *direct* PySide6 /
PyQt6 import into hydrus source.

The project rule (CLAUDE.md / docs/running_from_source.md) is to always go
through the qtpy wrapper so the code works under both PySide6 (default) and
PyQt6:  `from qtpy import QtWidgets as QW`.  Only a few binding-detection files
are allowed to import the bindings directly; they are allowlisted below.

Reads the PreToolUse hook payload (JSON) on stdin. Exits 2 with a message on
stderr to BLOCK the tool call; exits 0 to allow. Stdlib only -- runs under the
system python3, no venv needed.
"""

import json
import re
import sys

# path suffixes allowed to import the Qt bindings directly (binding selection /
# version probing). Verified against the tree: these are the only direct
# importers, everything else uses qtpy.
ALLOWLIST = (
    'hydrus/client/gui/QtInit.py',
    'hydrus/client/gui/QtInitImportTest.py',
    'hydrus/client/gui/ClientGUIAboutWindow.py',
)

# `import PySide6...` / `from PyQt6 import ...` etc., at the start of a line
DIRECT_IMPORT = re.compile( r'^[ \t]*(?:import|from)[ \t]+(PySide6|PyQt6)\b', re.MULTILINE )


def added_text( tool_input ):

    # every chunk of new text this tool call would write into the file
    parts = []

    if 'content' in tool_input:                     # Write

        parts.append( tool_input[ 'content' ] )


    if 'new_string' in tool_input:                  # Edit

        parts.append( tool_input[ 'new_string' ] )


    for edit in tool_input.get( 'edits', [] ):      # MultiEdit

        parts.append( edit.get( 'new_string', '' ) )


    return '\n'.join( parts )


def main():

    try:

        payload = json.load( sys.stdin )

    except Exception:

        sys.exit( 0 )   # can't parse the payload -> never get in the way


    tool_input = payload.get( 'tool_input', {} )
    path = tool_input.get( 'file_path', '' )

    if not path.endswith( '.py' ) or '/hydrus/' not in path:

        sys.exit( 0 )


    if any( path.endswith( allowed ) for allowed in ALLOWLIST ):

        sys.exit( 0 )


    match = DIRECT_IMPORT.search( added_text( tool_input ) )

    if match is None:

        sys.exit( 0 )


    binding = match.group( 1 )

    sys.stderr.write(
        f'Blocked: direct `{binding}` import in {path}.\n'
        'This project goes through the qtpy wrapper so it runs under both PySide6 '
        f'and PyQt6 -- use `from qtpy import QtWidgets as QW` (QtCore, QtGui, ...) '
        f'instead of importing {binding} directly. See CLAUDE.md. The only '
        'sanctioned direct importers are the binding-detection files (QtInit.py, '
        'QtInitImportTest.py, ClientGUIAboutWindow.py).\n'
    )
    sys.exit( 2 )


if __name__ == '__main__':

    main()
