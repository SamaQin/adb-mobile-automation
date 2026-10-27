# Repository Notes

## Runtime

- The supported local environment is Windows Python 3.12 in `.venv`; launch with `.venv\Scripts\python.exe fgo_bot.py` from the repository root.
- `AdbClient` prefers the bundled root `adb.exe` and falls back to `adb` on `PATH`. Real device workflows require USB debugging authorization and cannot be validated by unit tests alone.
- Runtime paths are anchored to the directory containing `fgo_bot.py`, not the caller's working directory: presets are in `fgo_config.json` and captured templates are in `fgo_templates/`.
- `fgo_config.json` is user state. `ConfigStore.load()` migrates the legacy `{support_pos, start_pos}` shape to schema version 2; preserve that migration when changing the schema.

## Architecture

- `fgo_bot.py` is a compatibility-named GUI entrypoint for the generic ADB automation app. Device subprocess handling is in `fgo_automation/device.py`; OpenCV file/matching operations are in `vision.py`; ordered execution and failure control are in `engine.py`.
- Step types are registered in `fgo_automation/steps.py`. A new type needs one runner plus a `StepDefinition`; the GUI generates its editor from the definition's `FieldSpec` entries.
- Presets own ordered `Step` objects. `on_failure="continue"` is what implements optional recognition; do not put branching behavior in the GUI.
- `Step.depends_on` references earlier steps by ID; the engine re-evaluates it from scratch each loop cycle, so a step is skipped when any prerequisite failed-with-continue, was disabled, or was itself skipped. Deletion and reordering must keep references valid via `normalize_dependencies`; duplicating a preset must remap step IDs and `depends_on` together.
- `Preset.loop_count` controls whole-preset repetition: `1` is the default and `0` means repeat until an unhandled failure or manual stop. Infinite presets with no enabled steps must fail instead of busy-looping.
- Tk calls stay on the main thread. Preset execution runs in a daemon worker and communicates through `AutomationConsole.events`; device waits must remain interruptible through `RuntimeContext.wait()`.
- ROI, point, and swipe-selection windows receive desktop bounds from Tk and display scaled screenshots; `vision.py` must convert selections back to original device pixels before templates or input coordinates are persisted.

## Verification

- Run focused tests with `.venv\Scripts\python.exe -m unittest discover -s tests -v`.
- Run a syntax/import-independent check with `.venv\Scripts\python.exe -m compileall -q fgo_bot.py fgo_automation tests`.
- Tests cover failure control with a fake registry, config migration, and synthetic OpenCV matching. ROI windows and ADB input still require a connected device and manual verification.
