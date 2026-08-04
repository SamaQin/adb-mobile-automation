from __future__ import annotations

import argparse
from threading import Timer
import webbrowser

import uvicorn

from web_server import app


def main() -> None:
    parser = argparse.ArgumentParser(description="ADB 图像自动化控制台 Web 服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--no-browser", action="store_true")
    options = parser.parse_args()

    if not options.no_browser and options.host in {"127.0.0.1", "localhost"}:
        browser_timer = Timer(
            0.8,
            lambda: webbrowser.open(f"http://127.0.0.1:{options.port}"),
        )
        browser_timer.daemon = True
        browser_timer.start()
    uvicorn.run(app, host=options.host, port=options.port, log_level="info")


if __name__ == "__main__":
    main()
