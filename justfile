# Hydrus Network — common dev commands.
# Run `just` or `just --list` to see everything.
#
# NOTE: hydrus must run from its venv, never the system python. `just` runs
# each recipe line in its own shell, so `source venv/bin/activate` would NOT
# persist between lines — so we always call the venv interpreter directly.

# venv interpreter (override on the CLI, e.g. `just python=venv313/bin/python run`)
python := if os_family() == "windows" { "venv/Scripts/python" } else { "venv/bin/python" }

# Default: list recipes.
default:
    @just --list

# --- setup ------------------------------------------------------------------

# Create / rebuild the venv. Interactive by default; `just setup -i=s` (simple)
# or `just setup -i=a` (advanced / test versions, for Python 3.14+) to skip prompts.
setup *args:
    ./setup_venv.py {{args}}

# Install the docs toolchain into the venv (run once before `just docs`).
docs-deps:
    {{python}} -m pip install mkdocs-material

# --- run --------------------------------------------------------------------

# Launch the client. Extra args pass through, e.g. `just run -d=/path/to/db`.
run *args:
    {{python}} hydrus_client.py {{args}}

# Launch the server.
server *args:
    {{python}} hydrus_server.py {{args}}

# TEMP, for developing the tag-graph feature: boot with real sample data, auto-cleaned on quit.
run-with-sample *args:
    {{python}} dev_run_with_sample.py {{args}}

# --- tests ------------------------------------------------------------------

# Run the full test suite (boots a real QApplication).
test:
    {{python}} hydrus_test.py

# Run one suite, e.g. `just test-only client_db`. Names: all, gui, client_api,
# daemons, data, search, tags, tags_fast, client_db, server_db, db,
# db_duplicates, duplicates_auto_resolution, networking, subscriptions, image,
# metadata_migration, server  (see hydrus/test/TestController.py).
test-only suite:
    {{python}} hydrus_test.py {{suite}}

# Run tests headless (no visible Qt windows) — good for CI / over SSH.
test-headless *args:
    QT_QPA_PLATFORM=offscreen {{python}} hydrus_test.py {{args}}

# Boot the client and screenshot its main window, fully headless.
# Delegates to the run-hydrus skill driver. e.g. `just shot /tmp/hydrus.png`
shot out="/tmp/hydrus.png":
    bash .claude/skills/run-hydrus/driver.sh shot {{out}}

# --- docs -------------------------------------------------------------------

# Build the help site into ./help (the canonical helper; manages the venv itself).
help:
    ./setup_help.py

# Build the offline docs into ./help via mkdocs directly (needs `just docs-deps`).
docs:
    {{python}} -m mkdocs build -d help -f mkdocs-offline.yml

# Serve docs with live reload at http://127.0.0.1:8000/
docs-serve:
    {{python}} -m mkdocs serve

# --- housekeeping -----------------------------------------------------------

# Pull the latest source (your db dir is gitignored and untouched).
update:
    git pull

# Show the current hydrus version from pyproject.toml.
version:
    @grep '^version' pyproject.toml
