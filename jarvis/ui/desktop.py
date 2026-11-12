"""The desktop window: a native window (pywebview) showing the local page,
plus an icon in the system tray (pystray).

On Windows, pywebview uses the Edge WebView2 runtime that ships with
Windows 10/11, so there is no browser to install.

With the tray icon, closing the window hides it instead of quitting.
JARVIS keeps running: the wake word still listens and scheduled items still
fire. Right-click the tray icon to open the window, stop everything, or
quit. If the tray library is not installed, closing the window quits, as
before.
"""

from __future__ import annotations

import os
import time
import webbrowser

from jarvis.core.agent import Jarvis
from jarvis.ui.server import serve
from jarvis.ui.shortcut import ICON


def run_window(jarvis: Jarvis, start_hidden: bool = False) -> None:
    try:
        import webview  # the pywebview package
    except ImportError:
        print('The desktop window needs pywebview:  pip install -e ".[desktop]"')
        print("Opening in your browser instead.")
        run_browser(jarvis)
        return
    # Let the page play sound and use the microphone without a click first.
    # Needed for the wake word and spoken reminders when JARVIS starts hidden.
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--autoplay-policy=no-user-gesture-required")

    _, url, app = serve(jarvis)
    time.sleep(0.5)  # give the server a moment to start listening
    state = {"quitting": False, "told": False}
    window = webview.create_window("JARVIS", url, width=1180, height=780, min_size=(480, 480), hidden=start_hidden)
    tray = _start_tray(window, jarvis, app, state)

    if tray is not None:
        def on_closing():
            if state["quitting"]:
                return True
            window.hide()
            if not state["told"]:
                state["told"] = True
                _notify(tray, "JARVIS is still running", "It is in the tray, by the clock. Right-click the icon to quit.")
            return False  # cancel the close

        window.events.closing += on_closing

    webview.start()  # blocks until the window is destroyed
    app.state.scheduler.stop()
    if tray is not None:
        try:
            tray.stop()
        except Exception:
            pass


def _notify(tray, title: str, text: str) -> None:
    try:
        tray.notify(text, title)
    except Exception:
        pass  # notifications are a nicety; never let one break anything


def _start_tray(window, jarvis: Jarvis, app, state: dict):
    """Returns the running tray icon, or None if it cannot be shown."""
    try:
        import pystray
        from PIL import Image
    except ImportError:
        return None

    def open_window(icon=None, item=None):
        window.show()
        try:
            window.restore()
        except Exception:
            pass

    def emergency_stop(icon=None, item=None):
        jarvis.kill.trip()
        jarvis.log.record("kill_switch", detail="tripped from the tray icon")
        _notify(icon, "JARVIS stopped", "Emergency stop engaged. Open JARVIS and type /resume to clear it.")

    def quit_app(icon=None, item=None):
        state["quitting"] = True
        window.destroy()

    try:
        icon = pystray.Icon(
            "JARVIS",
            Image.open(ICON),
            "JARVIS",
            menu=pystray.Menu(
                pystray.MenuItem("Open JARVIS", open_window, default=True),  # also runs on double-click
                pystray.MenuItem("Emergency stop", emergency_stop),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit", quit_app),
            ),
        )
        icon.run_detached()  # its own thread; the window keeps the main one
    except Exception as exc:
        jarvis.log.record("error", detail=f"tray icon unavailable: {type(exc).__name__}: {exc}")
        return None
    app.state.notify = lambda title, text: _notify(icon, title, text)
    return icon


def run_browser(jarvis: Jarvis) -> None:
    thread, url, _app = serve(jarvis)
    time.sleep(0.5)
    print(f"JARVIS is running at {url}  (Ctrl+C to quit)")
    webbrowser.open(url)
    try:
        while thread.is_alive():
            thread.join(timeout=0.5)
    except KeyboardInterrupt:
        pass
