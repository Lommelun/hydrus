---
name: run-hydrus
description: Build, run, test, screenshot, and drive (click/type/assert) the Hydrus Network client from source. Use when asked to start hydrus, run its test suite (run a single suite), boot the client, take a screenshot of its GUI, or interact with / drive the running app.
---

Hydrus is a PySide6 (Qt) desktop client that runs from source off SQLite. There is no compile step, but it needs a venv. Drive it with **`.claude/skills/run-hydrus/driver.sh`** — it builds the venv, runs test suites headless, and (the non-obvious part) **screenshots the GUI from inside the process via `screenshot.py`**, so it works with no display and no macOS Screen-Recording permission.

All paths below are relative to the repo root (the dir with `hydrus_client.py`). The driver self-locates, so you can run it from anywhere. Verified on macOS (Darwin, arm64, Python 3.13).

## Prerequisites

```bash
# uv (env builder) and Python 3.13 — the only hard requirements to boot:
brew install uv python@3.13
```

Optional, only for importing/playing **video**: `brew install ffmpeg` and a `libmpv` (`brew install mpv`). The client boots fine without them — it just shows a dismissible popup and disables those features. On macOS, leave media playback on the native viewer (mpv tends to crash the Mac client).

## Setup (one time, ~2–4 min, downloads PySide6/opencv/twisted)

```bash
bash .claude/skills/run-hydrus/driver.sh setup
```

This creates `venv/` with the project's dependencies, then **removes the `hydrus` package itself** so the app runs from the source tree, and adds `httmock` (a test-only dep missing from `pyproject.toml`). Equivalent raw commands if you skip the driver:

```bash
uv venv venv --python 3.13
uv pip install --python venv/bin/python .
uv pip uninstall --python venv/bin/python hydrus
uv pip install --python venv/bin/python httmock
```

## Run — agent path (headless, the one you want)

**Tests** — the real `QApplication` boots and runs a suite. This is the harness for verifying most changes:

```bash
bash .claude/skills/run-hydrus/driver.sh test            # default 'data' suite (115 tests, ~21s)
bash .claude/skills/run-hydrus/driver.sh test tags_fast  # one suite (24 tests, <1s, exits 0 on macOS)
```

Suite names live in `module_lookup` in `hydrus/test/TestController.py`: `all`, `gui`, `client_api`, `daemons`, `data`, `search`, `tags`/`tags_fast`, `client_db`, `server_db`, `db`, `db_duplicates`, `duplicates_auto_resolution`, `networking`, `subscriptions`, `image`, `metadata_migration`, `server`. The bare command is `QT_QPA_PLATFORM=offscreen venv/bin/python hydrus_test.py <suite>`.

> **Read the summary line, not just the exit code.** The runner calls `sys.exit(1)` if *any* test fails, and on **macOS the default `data` suite has one known failure** → `driver.sh test` **exits 1 on macOS** (`Ran 115 tests ... FAILED (failures=1)`). The failure is `test_SERIALISABLE_TYPE_SHORTCUT`: it asserts `command+alt+home` but Qt renders Alt as `option` on Mac — cosmetic, not a regression. On Linux/CI the `data` suite is clean (exit 0). If you want a guaranteed-green smoke check on macOS, use `test tags_fast`.

**Screenshot** — boots the client and grabs its main window to a PNG, fully headless:

```bash
bash .claude/skills/run-hydrus/driver.sh shot /tmp/hydrus.png
```

Internally: `HYDRUS_DB=<tmp> HYDRUS_SHOT=/tmp/hydrus.png QT_QPA_PLATFORM=offscreen venv/bin/python .claude/skills/run-hydrus/screenshot.py`. It boots against a throwaway db (under `$TMPDIR/run-hydrus`), waits `HYDRUS_SHOT_DELAY` seconds (default 22) for the GUI to build, then `QWidget.grab().save()`s the largest visible top-level window. Output is ~796×796 (the offscreen default geometry). **Open the PNG and confirm it shows the menu bar + search/tags panels — not a blank surface.**

**Drive it (click / type / assert)** — interact with the running app to verify UI behaviour, fully headless:

```bash
bash .claude/skills/run-hydrus/driver.sh drive /tmp/shots   # prints a PASS/FAIL report + step PNGs
```

This runs `drive_example.py`, which injects **synthetic Qt events** (`QTest.keyClicks` / `QTest.mouseClick`) into real widgets and reads hydrus's own state back to assert. The bundled example types `system:inbox` into the tag autocomplete (keyboard) and clicks the "searching immediately" toggle (mouse), asserting `OnOffButton.IsOn()` flips `True→False` (label → "search paused"). To drive your own flow, copy `drive_example.py` and edit `step0/step1/step2`: locate widgets with `main.findChildren(<QtClass>)` matched on `.metaObject().className()` / `.text()`, act with `QTest`/`QAction.trigger()`, and assert via the widget's own methods.

> **Driving is in-process on purpose.** Because the code runs inside the hydrus process it injects events straight into the Qt event loop and can read widget state — so it needs no display and **no OS permission**, and works in CI. OS-level input (CGEvent/AppleScript) would need a real window, macOS **Accessibility** permission (separate from Screen-Recording), and pixel coordinates, and can't assert state. Don't use it.

## Run — human path (real window, needs a display)

```bash
bash .claude/skills/run-hydrus/driver.sh run     # launches GUI against a throwaway db; Ctrl-C to quit
bash .claude/skills/run-hydrus/driver.sh stop    # or stop the backgrounded one
```

For real use, run `venv/bin/python hydrus_client.py -d /path/to/db` (or `just run`). Useless headless — it just opens and waits.

## Gotchas (battle scars from building this)

- **Prefer the in-process Qt grab over OS capture.** macOS `screencapture -l <id>` / Quartz `CGWindowListCreateImage` only work if the controlling terminal has been granted **Screen-Recording** permission (without it: "could not create image from window"), need a real on-screen window, and may capture mid-boot (blank body while the status bar shows "CPU busy"). The in-process `QWidget.grab()` has none of those constraints and works in CI/headless — so it's the default. OS capture's only upside is native Aqua styling at real Retina geometry, for human-facing shots; not needed for automation.
- **Do not `pip install .` and then run the installed package.** The built wheel ships a malformed `static/audio.png`, so boot dies with `DamagedOrUnusualFileException`. Always run from the source tree. `driver.sh setup` uninstalls the package for exactly this reason; `screenshot.py` also force-inserts the repo root at `sys.path[0]` (a script otherwise puts its *own* dir there, not the cwd).
- **Tests need a Qt-capable env.** They boot a `QApplication` and run on the Qt thread; `QT_QPA_PLATFORM=offscreen` makes that headless-safe.
- **`venv/` and `db/` are gitignored** — building the env and booting against a throwaway db leaves the working tree clean.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ModuleNotFoundError: No module named 'httmock'` | Test-only dep; `driver.sh setup` installs it (`uv pip install --python venv/bin/python httmock`). |
| `DamagedOrUnusualFileException: ...static/audio.png` | You're importing the installed `hydrus` package. Run from source / re-run `driver.sh setup` (it uninstalls the package). |
| `shot` prints `no visible top-level window yet` | GUI didn't finish booting in time — raise `HYDRUS_SHOT_DELAY` (e.g. `HYDRUS_SHOT_DELAY=35`). First-ever boot compiles bytecode and is slower. |
| GUI popup about mpv/FFMPEG on boot | Expected without `libmpv`/`ffmpeg`; dismissable, only affects video. |
