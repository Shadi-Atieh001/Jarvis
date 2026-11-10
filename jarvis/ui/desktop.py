"""The desktop window: a native window (pywebview) showing the local page.

On Windows, pywebview uses the Edge WebView2 runtime that ships with
Windows 10/11, so there is no browser to install.
"""

from __future__ import annotations

import time
import webbrowser

from jarvis.core.agent import Jarvis
from jarvis.ui.server import serve


def run_window(jarvis: Jarvis) -> None:
    try:
        import webview  # the pywebview package
    except ImportError:
        print('The desktop window needs pywebview:  pip install -e ".[desktop]"')
        print("Opening in your browser instead.")
        run_browser(jarvis)
        return
    _, url = serve(jarvis)
    time.sleep(0.5)  # give the server a moment to start listening
    webview.create_window("JARVIS", url, width=920, height=760, min_size=(480, 480))
    webview.start()  # blocks until the window is closed


def run_browser(jarvis: Jarvis) -> None:
    thread, url = serve(jarvis)
    time.sleep(0.5)
    print(f"JARVIS is running at {url}  (Ctrl+C to quit)")
    webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
