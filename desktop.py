"""Native desktop shell.

Runs the FastAPI app on a loopback port in a background thread and hosts the
UI in the platform's own web view (WKWebView on macOS, WebView2 on Windows),
so the result is an ordinary application window rather than a browser tab.

Zoom, find, and section navigation are implemented in the page itself
(static/js/shortcuts.js) so they behave the same on both platforms; the native
menu bar below just calls into them.
"""
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn
import webview
from webview.menu import Menu, MenuAction, MenuSeparator

HOST = "127.0.0.1"
TITLE = "AI Systematic Review Screening Assistant"


def find_free_port() -> int:
    """Let the OS pick a free loopback port; nothing else may bind it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as r:
                if r.status == 200:
                    return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.1)
    return False


def serve(port: int) -> None:
    from app.main import app
    uvicorn.run(app, host=HOST, port=port, log_level="warning", access_log=False)


def build_menu(window) -> list:
    def js(code):
        return lambda: window.evaluate_js(code)

    return [
        Menu("View", [
            MenuAction("Zoom In", js("window.appShortcuts.zoomIn()")),
            MenuAction("Zoom Out", js("window.appShortcuts.zoomOut()")),
            MenuAction("Actual Size", js("window.appShortcuts.zoomReset()")),
            MenuSeparator(),
            MenuAction("Reload", js("location.reload()")),
        ]),
        Menu("Go", [
            MenuAction("Projects", js("window.go('projects')")),
            MenuAction("Criteria", js("window.go('criteria')")),
            MenuAction("Import", js("window.go('import')")),
            MenuAction("Screen", js("window.go('screen')")),
            MenuAction("Results", js("window.go('results')")),
            MenuAction("Settings", js("window.go('settings')")),
        ]),
        Menu("Help", [
            MenuAction("Find in Page", js("window.appShortcuts.find()")),
            MenuAction("Keyboard Shortcuts", js("window.appShortcuts.help()")),
        ]),
    ]


def main() -> int:
    port = find_free_port()
    url = f"http://{HOST}:{port}"

    threading.Thread(target=serve, args=(port,), daemon=True).start()
    if not wait_for_server(f"{url}/api/health"):
        # No window yet, so there is nowhere to show this but the console.
        print("AI Screening: the local server did not start.", file=sys.stderr)
        return 1

    window = webview.create_window(
        TITLE, url,
        width=1280, height=860,
        min_size=(900, 600),
        text_select=True,
        confirm_close=False,
    )
    webview.start(menu=build_menu(window))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
