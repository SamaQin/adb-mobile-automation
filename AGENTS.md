# Repository Notes

## Runtime

- Supported environment: Windows Python 3.12 in `.venv`; launch `.venv\Scripts\python.exe main.py` from the repository root. Default URL is `http://127.0.0.1:8001`; `--no-browser` disables automatic browser launch.
- Frontend: Vue 3, Pinia and Vue Flow in `web/`. Run `npm run build` there after source changes. The backend serves `web/dist`; Vite development mode proxies to backend port 8000.
- `AdbClient` prefers root `adb.exe` and falls back to `adb` on PATH. Real device workflows require USB debugging authorization and manual verification.
- Runtime data is rooted beside the source entrypoint or packaged executable: `config.json` and `templates_file/`. Preserve user data and the legacy `{support_pos, start_pos}` configuration migration.

## Architecture

- `main.py` launches `web_server`. Device commands, image operations and ordered execution live in `model_automation/device.py`, `vision.py` and `engine.py`.
- Step types are registered in `model_automation/steps.py`. New types require a runner and `StepDefinition`; the frontend builds editors from `FieldSpec`. Validate complete parameters before device actions, using the shared field validation.
- Presets own ordered steps, with dependencies, template branches and backward return targets. Canvas edges visualize these semantics; do not introduce a separate frontend execution model.
- Dependencies reference earlier steps in the same layer. Reordering/deletion must normalize references. Duplication must remap nested IDs, dependencies and return targets together.
- `loop_count=1` runs once; `0` repeats until failure or stop. Infinite presets with no enabled steps must fail without busy-looping. Waits use interruptible `RuntimeContext.wait()`.
- Runtime execution uses a worker thread. Backend writes must use `RuntimeManager.mutation()` so read-modify-write and start admission are mutually exclusive. Never hold a threading lock across `await`; prepare uploads asynchronously and commit in a synchronous worker transaction.
- The engine emits frame/cycle/step/jump events through the optional `RuntimeContext.event` callback. Child contexts must preserve callback/run identity through `dataclasses.replace`. Display logs must not drive real engine state; log parsing is only a compatibility adapter for older injected engines.
- WebSocket queues and pending callbacks are bounded; slow subscribers disconnect and reconnect. Envelopes carry server/run identities and monotonic sequence numbers; initial subscriptions replay display logs and finish with an authoritative node/frame snapshot. Ordinary step progress stays incremental.
- `vision.load_template` caches read-only color/grayscale data with LRU entry/byte limits and file-stat invalidation; `load_image` remains independently editable. ROI fields use original device pixels and exclusive right/bottom bounds; archive scaling must transform both rectangle endpoints.
- Screencast defaults to length-prefixed JPEG for compatibility; `?codec=h264` sends session/config/key/delta packet records for WebCodecs. Never drop arbitrary delta packets and continue decoding; resynchronize at a keyframe. Browser failures fall back to JPEG and must close decoder, VideoFrames and readers.
- Canvas topology, data bindings and layout updates are separate. Ordinary property edits must not rebuild the graph or clear all edges. Vue Flow nodes must be registered before publishing their edges; preserve update-generation checks across asynchronous updates. Runtime node changes use the bounded revision journal and step/adjacent-edge index; avoid deep-watching the full state map.
- Published runtime envelopes and H.264 packet bytes are shared read-only across live subscriber queues; copy at input/public snapshot boundaries. Idle close must recheck subscribers atomically. Check stop requests between screenshot/matching and each new device action; an in-flight ADB command still uses its timeout.
- Logs are immutable rows in replaced raw arrays. Append through runStore actions so deduplication, limits and UI notifications stay correct. Keep scroll following at the tail and preserve the user's historical row anchor.
- History stores only serialized snapshots, with a shared 16 MiB/50-entry undo+redo budget; one oversized nearest snapshot is retained as an exception. Batch copy/delete must remap all selected root subtrees in one transaction. Template catalogs coalesce requests, invalidate after writes/import, and render bounded pages.
- Device dimensions may be reused for only 0.5 seconds to coalesce health checks. Screenshots are always fresh; resolution-sensitive imports force a dimension refresh, and disconnect/errors invalidate the cache.
- Multi-node movement commits all final positions once. Batch edits record one undo entry. Config and loaded layout state are restored together; saving advances the saved baseline without clearing history. Save responses must not overwrite newer edits.
- Screenshot editors display scaled images but persist original device pixel coordinates.

## Verification

- Backend: `.venv\Scripts\python.exe -m unittest discover -s tests -v`.
- Syntax: `.venv\Scripts\python.exe -m compileall -q main.py model_automation web_server tests`.
- Frontend, from `web/`: `npm test` and `npm run build`.
- Browser acceptance uses a disposable fake device/config: start `.venv\Scripts\python.exe -m uvicorn tests.e2e_web_app:app --host 127.0.0.1 --port 8002`, then set `PLAYWRIGHT_BASE_URL=http://127.0.0.1:8002` and run `npm run test:e2e` in `web/`. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can select an installed Edge/Chrome. Never run mutating acceptance against the user's production config.
- Device input, real screen recognition and scrcpy streaming still require authorized hardware verification.
