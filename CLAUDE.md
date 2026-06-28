# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Hydrus Network — a personal, booru-style media tagger and file manager. A Qt desktop **client** and an optional **server** (a shareable tag/file repository), both pure Python running off SQLite. It is a large, mature, single-developer codebase (~v676). Public pull requests are closed; this repo is a fork for local development.

## Running and building

The program **runs from source** — there is no compile step, but it requires a venv (see `docs/running_from_source.md`). A `justfile` wraps the common commands; run `just` (or `just --list`) to see them. Key flows:

- `just setup` → builds/rebuilds the `venv` via `./setup_venv.py` (interactive). Pass `-i=s` (simple) or `-i=a` (advanced/test versions) to skip prompts. **Re-run this whenever you move the install dir or hit a library-version error on boot.** On Python 3.14+ choose the advanced/`-i=a` path.
- `just run` → launches the client (`hydrus_client.py`). `just server` for the server.
- `just test` → full suite; `just test-only <module>` for one suite; `just test-headless` for offscreen Qt.
- `just docs` / `just docs-serve` → build/serve the help site (needs `just docs-deps` once).

**Never invoke `hydrus_client.py` / `hydrus_server.py` / `hydrus_test.py` with the system Python** — they fail with missing-library errors (`yaml`, `qtpy`, …). Always use the venv interpreter (`venv/bin/python`, or `venv/Scripts/python` on Windows). `just` recipes already do this; each `just` recipe line runs in its own shell, so `source venv/bin/activate` does **not** carry between lines — call the interpreter directly.

The runtime database lives in `db/` by default (gitignored) or wherever `-d/--db_dir` points. See `docs/launch_arguments.md` for flags like `--db_journal_mode`, `--profile_mode`, `--pause_network_traffic`.

### Tests

Tests use a custom runner (`hydrus_test.py` → `TestController`), **not** pytest. It boots a real `QApplication` and runs suites on the Qt thread, so a Qt-capable environment is required (use `QT_QPA_PLATFORM=offscreen` for headless/CI). The first CLI arg selects one named suite; no arg runs everything.

```
python hydrus_test.py            # all
python hydrus_test.py client_db  # one suite
```

Suite names are defined in `module_lookup` in `hydrus/test/TestController.py`. Common ones: `all`, `gui`, `client_api`, `daemons`, `data`, `search`, `tags` / `tags_fast`, `client_db`, `server_db`, `db`, `db_duplicates`, `duplicates_auto_resolution`, `networking`, `subscriptions`, `image`, `metadata_migration`, `server`. Test modules live in `hydrus/test/` as `Test*.py`.

## Architecture (the big picture)

Read these together — the design is consistent across client and server.

**Entry points & boot.** `hydrus_client.py` / `hydrus_server.py` / `hydrus_test.py` are thin shims that call `hydrus/hydrus_*_boot.py`. The boot modules parse args, initialise Qt (`hydrus/client/gui/QtInit.py`) and logging *before* almost anything else (note the deliberate early `import dateparser` + `locale.setlocale` for timezone-cache correctness), then construct and `Run()` the Controller.

**Controller singletons.** Everything hangs off one Controller object. `hydrus/core/HydrusController.py` is the base; `hydrus/client/ClientController.py` and `hydrus/server/ServerController.py` extend it. The Controller owns the DB, the thread pools, the pubsub bus, the network engine, the GUI, and the manager objects. It is reached globally:
- `from hydrus.core import HydrusGlobals as HG` → `HG.controller`
- `from hydrus.client import ClientGlobals as CG` → `CG.client_controller`
- `from hydrus.server import ServerGlobals as SG`

These `*Globals` modules are mutable module-level namespaces holding the singletons and many global flags — this is the project's dependency-injection mechanism. Expect to see `CG.client_controller.<something>` everywhere.

**Database: single thread, async access, many modules.** All DB work happens on **one dedicated DB thread** with a single SQLite connection (plus ATTACHed dbs). Other threads never touch SQLite directly — they marshal jobs through the Controller:
- `CG.client_controller.Read( 'action', ... )` → synchronous read returning a value.
- `CG.client_controller.Write( 'action', ... )` → write job (async by default; `WriteSynchronous` to block).

The monolithic DB class (`hydrus/client/db/ClientDB.py`, `hydrus/server/ServerDB.py`) dispatches those action strings to methods. Functionality is split across ~45 `ClientDBModule` subclasses in `hydrus/client/db/` (e.g. `ClientDBMappingsStorage`, `ClientDBFilesStorage`, `ClientDBTagSiblings`, `ClientDBSimilarFiles`). `ClientDB.py` imports and registers all of them; a module declares the tables it owns and the cross-module services it needs. When adding DB behaviour, add/extend a module and a dispatched action rather than opening SQLite elsewhere.

**PubSub.** `hydrus/core/HydrusPubSub.py`, used via `controller.pub( topic, ... )` / `controller.sub( obj, method, topic )`. This is the decoupled messaging bus — heavily used to push updates from the model/DB threads to the Qt GUI (e.g. `'message'`, `'notify_new_sessions'`). Use `pubimmediate` only when you must run synchronously.

**Serialisation.** `hydrus/core/HydrusSerialisable.py` is how nearly every persistent or transmissible object is stored and sent. Such objects subclass `SerialisableBase` / `SerialisableBaseNamed`, register a unique `SERIALISABLE_TYPE_*` constant and version, and implement `_GetSerialisableInfo` / `_InitialiseFromSerialisableInfo` (plus `_UpdateSerialisable` for version migrations). The same mechanism backs the DB, the network protocol, and the Client API. **Any new savable object must register a type and handle version bumps** — search existing subclasses for the pattern before inventing storage.

**GUI (Qt via qtpy).** Lives in `hydrus/client/gui/`. The project supports **both** PySide6 (default) and PyQt6 through the `qtpy` wrapper. **Always `from qtpy import QtWidgets as QW` etc. — never import `PySide6`/`PyQt6` directly.** `QtInit.py` handles binding selection and monkeypatches. GUI runs on the main thread; use `ClientGUICallAfter` / the Controller's CallAfter helpers to hop work onto the Qt thread, and the `CallToThread*` pools to hop off it.

**Client API.** A Twisted HTTP service (`hydrus/client/networking/`, surfaced via `hydrus/client/ClientAPI.py`) that exposes most client functionality over JSON; it is fully documented in `docs/client_api.md`. The server's repository protocol is similarly Twisted-based under `hydrus/server/networking/`.

**Code layout.** `hydrus/core/` = shared infra (DB base, data types, paths, time, sessions, networking primitives — `Hydrus*` names). `hydrus/client/` = client logic, with `Client*` top-level files and topical subpackages (`db`, `gui`, `importing`, `media`, `metadata`, `networking`, `parsing`, `search`, `duplicates`, `files`). `hydrus/server/` = server. `hydrus/test/` = tests. `hydrus/external/` = vendored third-party helpers.

## Code style — match it, do not "fix" it

The author's style is deliberate and unusual; the maintainer explicitly does **not** want refactoring or normalisation (see "My Code" in `docs/running_from_source.md`). When editing, mirror the surrounding code exactly:

- **Spaces inside parentheses/brackets:** `def Foo( self, x ):`, `func( a, b )`, `d[ 'key' ]`, `list[ 0 ]`.
- **Blank lines are indented to the block** and `.editorconfig` sets `trim_trailing_whitespace = false` — these are intentional. Do not strip trailing whitespace or "clean up" blank lines; it produces noisy, unwanted diffs.
- 4-space indent, LF endings, UTF-8, final newline (`.editorconfig`).
- Verbose, explicit, vertical code with generous blank lines between logical steps; CamelCase methods. Prefer following the local idiom over applying general Python conventions, PEP 8, or auto-formatters.

## Supplementary reference

- `docs/` is the full user/developer manual (Markdown, built with MkDocs). Notable: `running_from_source.md`, `developer_api.md` / `client_api.md`, `launch_arguments.md`, `database_migration.md`, `downloader_*` (the downloader/parser system), `duplicates.md`.
- **DeepWiki AI crawl: https://deepwiki.com/hydrusnetwork/hydrus** — an AI-analyzed overview of this codebase that the maintainer endorses (in `running_from_source.md`). Useful for orienting on cross-cutting systems, but treat the source as ground truth where they differ.
