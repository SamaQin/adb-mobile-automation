from __future__ import annotations

import argparse
import os
import sys
from threading import Timer
import webbrowser

import uvicorn

from web_server import app


def _ensure_stdio() -> None:
    """Windowed (console=False) 打包下 stdout/stderr 为 None，uvicorn 日志会崩溃，这里兜底。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def main() -> None:
    _ensure_stdio()
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
