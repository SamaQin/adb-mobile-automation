# ADB Automation Workbench

A Windows desktop automation tool for Android devices. It uses ADB to capture device screens and send touch input, while OpenCV matches screen regions against image templates. Build workflows visually in a browser, then run them as ordered, repeatable presets.

[简体中文文档](README.zh-CN.md)

## Features

- Visual workflow canvas with draggable nodes, connections, grouping, and automatic layout.
- Image recognition with configurable similarity thresholds, retries, multiple templates, and optional continuation after a failed step.
- Coordinate taps, repeated taps, swipes, waits, nested preset execution, and loop control.
- Screenshot-based coordinate and swipe selection. Selections are converted back to the device's original pixel coordinates.
- Live run status, per-step results, logs, and device connection checks.
- Low-latency H.264 screen mirroring in a floating window. The monitor can be freely moved, resized, and hidden while you work, and its position and size are remembered.
- User configuration and image templates stored beside the application for easy backup.

## Requirements

For a source checkout on Windows:

- Windows 10 or later.
- Python 3.12.
- Node.js and npm (only needed to build or develop the web UI).
- An Android device with USB debugging enabled and authorized for this computer.

The project includes `adb.exe` and its Windows support DLLs at the repository root. The application uses this bundled ADB first and falls back to `adb` on `PATH` if the bundled executable is unavailable. The target computer may also need the device manufacturer's USB driver.

The live monitor uses a bundled, unmodified [scrcpy](https://github.com/Genymobile/scrcpy) server (`vendor/scrcpy-server-v5.0.1`, Apache License 2.0) and decodes its H.264 stream with PyAV. No separate scrcpy installation is required; see `vendor/README.md` for the source and checksum.

## Install and run from source

Run commands from the repository root in Windows PowerShell or Command Prompt.

1. Create a Python environment and install the backend dependencies:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Build the web interface (required for the normal single-server launch):

   ```powershell
   cd web
   npm install
   npm run build
   cd ..
   ```

3. Connect and authorize the Android device, then start the application:

   ```powershell
   .venv\Scripts\python.exe main.py
   ```

The server listens on `http://127.0.0.1:8001` and opens the browser automatically. To choose another port or keep the browser closed:

```powershell
.venv\Scripts\python.exe main.py --port 8080 --no-browser
```

Then open `http://127.0.0.1:8080` yourself. The service binds to localhost by default and is intended for local use.

### Frontend development mode

Start the backend from the repository root in one terminal:

```powershell
.venv\Scripts\python.exe main.py --port 8000 --no-browser
```

In a second terminal, start Vite:

```powershell
cd web
npm run dev
```

Open the URL printed by Vite. Its development proxy forwards API and WebSocket requests to the backend at `http://127.0.0.1:8000`.

Stop either process with `Ctrl+C`.

## Use the workbench

1. Connect the device over USB, enable **USB debugging**, accept the authorization prompt on the device, and click **Check device** in the top toolbar.
2. Select or create a preset. Drag a step from the left palette onto the canvas, or double-click it to add it.
3. Select a node to edit its properties in the right panel. Available operations include image recognition and tap, multi-tap, coordinate tap, swipe, wait, preset execution, and loop control.
4. For image recognition, add template images and set a similarity threshold. Configure retries and intervals when needed. A step can stop the preset on failure or continue to the next step.
5. Use the screenshot picker to capture a template region, select tap coordinates, or draw a swipe path. The app stores coordinates in the device's original resolution even when the preview is scaled.
6. Connect steps on the canvas to express prerequisites. A step is skipped in a cycle if a prerequisite was disabled, skipped, or failed with continuation enabled.
7. Set the preset loop count: `1` runs once; `0` repeats until a failure or a manual stop. Use **Run** to start and the stop control to interrupt execution.
8. Follow per-node states and the log panel to diagnose a run. Use the canvas fit, zoom, lock, and layout controls to navigate the workflow.
9. Click the smartphone icon in the top toolbar to open the floating live device monitor. It streams the device display as low-latency H.264 at up to 30 FPS. Drag its title bar to move it, drag the bottom-right corner to resize it, and click the eye button to hide it. The stream stops when hidden or when the page is in the background, and the window remembers its last position and size.

## Data and backups

The application creates `config.json` and `templates_file/` in the project root on first use. In a PyInstaller build, they are created beside the executable. Back up both before replacing or upgrading the application. Do not place a packaged copy in a protected directory such as `C:\Program Files`, because the application needs write access to its data directory.

The configuration loader migrates supported legacy configurations when they are opened. Keep a backup before manually editing configuration files.

## Build a distributable Windows app

The PyInstaller spec creates a one-folder distribution that includes the Python runtime, web assets, ADB executable, and support DLLs. Build on Windows.

1. Install the source requirements and PyInstaller:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements.txt
   .venv\Scripts\python.exe -m pip install pyinstaller
   cd web
   npm install
   npm run build
   cd ..
   ```

2. Package the application:

   ```powershell
   .venv\Scripts\pyinstaller.exe --noconfirm ADB-Automation.spec
   ```

The executable is `dist\ADB-Automation\ADB-Automation.exe`. Distribute the **entire** `dist\ADB-Automation\` directory; the executable cannot run by itself. The target computer does not need Python or Node.js installed. The Android USB driver may still be required.

To inspect startup logs for a packaged build, launch the executable from a terminal. Change the port or suppress automatic browser opening with `--port PORT` and `--no-browser`.

## Troubleshooting

- **The browser cannot connect:** Confirm the backend is running, use the port shown by the launch command, and check whether another process already occupies it.
- **The device is not detected:** Enable USB debugging, accept the device authorization prompt, install the appropriate Windows USB driver, and verify that ADB can see the device.
- **The page is missing or stale in a packaged build:** Run `npm run build` in `web/` before packaging again.
- **A template is not recognized:** Confirm the template belongs to the same screen state and resolution, then adjust its similarity threshold and retry settings.
- **The app cannot save its data:** Move it to a directory where the current user has write permission.

## Tests and checks

Run from the repository root:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe -m compileall -q main.py model_automation web_server tests
cd web
npm test
npm run build
```

Device input and screenshot selection require a connected, authorized Android device and are not covered by unit tests.
