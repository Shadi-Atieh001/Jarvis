"""Desktop tools: see what is on screen and work the mouse and keyboard.

"Seeing" here means reading the text that Windows itself knows about each
window: titles, buttons, menus, text fields and their contents. This is the
same interface screen readers use (UI Automation). It works with a
text-only model and needs no screenshots. Its limit: apps that draw their
own interface (some games, video, images) expose little or nothing.

The Windows-specific code is confined to WindowsBackend at the bottom of
this file. Everything above it is ordinary Python and is covered by tests
using a stand-in backend.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from jarvis.core.tools import AUTO, BLOCKED, ToolContext, ToolResult, tool

MAX_ELEMENTS = 350
MAX_SCREEN_CHARS = 14_000


@dataclass
class Element:
    role: str  # Button, Edit, Text, MenuItem, ...
    name: str
    value: str  # contents of a text field, if any
    rect: tuple[int, int, int, int]  # left, top, right, bottom in screen pixels
    enabled: bool = True

    @property
    def centre(self) -> tuple[int, int]:
        left, top, right, bottom = self.rect
        return (left + right) // 2, (top + bottom) // 2


class DesktopUnavailable(Exception):
    pass


# The most recent read_screen result, so "click element 12" can find it.
_last_snapshot: list[Element] = []
_last_app: str | None = None  # the app that snapshot was of


def _app_for_click(args: dict, ctx: ToolContext) -> str | None:
    """Which app a click would land in: the one last read (for a click by
    element number), otherwise whichever is in front."""
    if args.get("element") is not None and _last_app:
        return _last_app
    return _front_app(args, ctx)


def _front_app(args: dict, ctx: ToolContext) -> str | None:
    """The app in front, which is where typing and key presses go."""
    try:
        find = getattr(_backend(), "front_app", None)
        return find() if find else None
    except Exception:
        return None
_backend_instance = None


def _backend():
    global _backend_instance
    if _backend_instance is None:
        if sys.platform != "win32":
            raise DesktopUnavailable("Screen reading and mouse/keyboard control only work on Windows.")
        _backend_instance = WindowsBackend()
    return _backend_instance


def _unavailable(exc: Exception) -> ToolResult:
    return ToolResult(str(exc), is_error=True)


# ----------------------------------------------------------------- seeing


@tool(
    name="list_windows",
    description="List the titles of the windows currently open on the desktop. The first one is the window in front.",
    input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: "List the open windows",
)
def list_windows(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        titles = _backend().windows()
    except DesktopUnavailable as exc:
        return _unavailable(exc)
    return ToolResult("\n".join(f"- {t}" for t in titles) or "No windows are open.", untrusted_source="window titles")


@tool(
    name="read_screen",
    description=(
        "Read what is in a window: its buttons, menus, text fields and text, each with a number. "
        "Defaults to the window in front; pass part of a title to choose another. "
        "Use the numbers with the click tool. Read again after anything changes, because the numbers change too."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "window": {"type": "string", "description": "Part of the window's title. Omit for the window in front."}
        },
        "additionalProperties": False,
    },
    tier=AUTO,
    read_only=True,
    kind="read",
    describe=lambda a, c: f"Read the contents of {a.get('window') or 'the window in front'}",
)
def read_screen(args: dict, ctx: ToolContext) -> ToolResult:
    global _last_snapshot, _last_app
    try:
        title, elements = _backend().snapshot(args.get("window"))
    except DesktopUnavailable as exc:
        return _unavailable(exc)
    _last_snapshot = elements[:MAX_ELEMENTS]
    _last_app = getattr(_backend(), "last_app", None)
    lines = [f'Window: "{title}"']
    for number, e in enumerate(_last_snapshot, 1):
        line = f"[{number}] {e.role}"
        if e.name:
            line += f' "{_short(e.name, 160)}"'
        if e.value and e.value != e.name:
            line += f" = {_short(e.value, 1500)!r}"
        if not e.enabled:
            line += " (disabled)"
        lines.append(line)
    if len(elements) > MAX_ELEMENTS:
        lines.append(f"... {len(elements) - MAX_ELEMENTS} more elements not shown.")
    if len(lines) == 1:
        lines.append("(This window exposes no readable contents.)")
    text = "\n".join(lines)
    if len(text) > MAX_SCREEN_CHARS:
        text = text[:MAX_SCREEN_CHARS] + "\n... (cut)"
    # What is on screen may include a web page or a document, so it is
    # labelled as data. It does not trigger extra confirmations: JARVIS
    # could not click anything if reading the screen did.
    return ToolResult(text, untrusted_source=f"screen: {title}")


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit] + "..."


# ------------------------------------------------------------- launching


def _start_menu_folders() -> list[Path]:
    folders = []
    for variable in ("APPDATA", "PROGRAMDATA"):
        base = os.environ.get(variable)
        if base:
            folders.append(Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs")
    return [f for f in folders if f.is_dir()]


def find_app(name: str, folders: list[Path] | None = None) -> Path | None:
    """Find a Start Menu shortcut whose name matches. Exact match wins,
    then 'starts with', then 'contains'."""
    wanted = name.strip().lower()
    best: tuple[int, int, Path] | None = None
    for folder in folders if folders is not None else _start_menu_folders():
        for shortcut in folder.rglob("*.lnk"):
            label = shortcut.stem.lower()
            if "uninstall" in label:
                continue
            rank = 0 if label == wanted else 1 if label.startswith(wanted) else 2 if wanted in label else None
            if rank is not None and (best is None or (rank, len(label)) < best[:2]):
                best = (rank, len(label), shortcut)
    return best[2] if best else None


@tool(
    name="open_app",
    description=(
        "Open an application by name, as it appears in the Start menu (for example 'Notepad', 'Chrome', "
        "'Spotify', 'File Explorer'). To open a file or folder instead, pass its full path."
    ),
    input_schema={
        "type": "object",
        "properties": {"name": {"type": "string", "description": "App name, or the full path of a file or folder."}},
        "required": ["name"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="launch",
    describe=lambda a, c: f"Open {a['name']}",
)
def open_app(args: dict, ctx: ToolContext) -> ToolResult:
    name = args["name"].strip().strip('"')
    if not name:
        return ToolResult("Which app?", is_error=True)
    target: str | None = None
    if os.path.exists(os.path.expanduser(name)):
        target = os.path.expanduser(name)
    else:
        shortcut = find_app(name)
        if shortcut:
            target = str(shortcut)
        elif shutil.which(name):
            target = shutil.which(name)
    if target is None:
        return ToolResult(f"No app called {name!r} was found in the Start menu. Check the name, or give a full path.", is_error=True)
    try:
        if sys.platform == "win32":
            os.startfile(target)  # opens it the way a double-click would
        else:
            subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", target])
    except OSError as exc:
        return ToolResult(f"Could not open {name}: {exc}", is_error=True)
    time.sleep(1.5)  # give the window a moment to appear
    return ToolResult(f"Opened {Path(target).stem}. Use read_screen to see its window.")


@tool(
    name="focus_window",
    description="Bring a window to the front, chosen by part of its title.",
    input_schema={
        "type": "object",
        "properties": {"window": {"type": "string", "description": "Part of the window's title."}},
        "required": ["window"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="launch",
    describe=lambda a, c: f"Bring the window '{a['window']}' to the front",
)
def focus_window(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        title = _backend().focus(args["window"])
    except DesktopUnavailable as exc:
        return _unavailable(exc)
    return ToolResult(f'"{title}" is now in front.')


# ------------------------------------------------------------ controlling


@tool(
    name="click",
    description=(
        "Click something on screen. Give 'element' (a number from the latest read_screen), or 'x' and 'y' in screen "
        "pixels. After clicking, call read_screen again to see the result."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "element": {"type": "integer", "minimum": 1, "description": "Number from the latest read_screen."},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right"], "description": "Default left."},
            "double": {"type": "boolean", "description": "Double-click. Default false."},
        },
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="control",
    target_app=_app_for_click,
    describe=lambda a, c: _describe_click(a),
)
def click(args: dict, ctx: ToolContext) -> ToolResult:
    target = _click_target(args)
    if isinstance(target, str):
        return ToolResult(target, is_error=True)
    (x, y), label = target
    ctx.kill.check()
    try:
        _backend().click(x, y, args.get("button", "left"), bool(args.get("double")))
    except DesktopUnavailable as exc:
        return _unavailable(exc)
    time.sleep(0.4)
    return ToolResult(f"Clicked {label}. Call read_screen to see what changed.")


def _click_target(args: dict):
    if args.get("element") is not None:
        index = args["element"]
        if not _last_snapshot:
            return "Call read_screen first; element numbers come from it."
        if index > len(_last_snapshot):
            return f"There is no element {index}; the latest read_screen listed {len(_last_snapshot)}."
        e = _last_snapshot[index - 1]
        if not e.enabled:
            return f'Element {index} ({e.role} "{e.name}") is disabled and cannot be clicked.'
        return e.centre, f'{e.role} "{_short(e.name, 60)}"'
    if args.get("x") is not None and args.get("y") is not None:
        return (args["x"], args["y"]), f"at ({args['x']}, {args['y']})"
    return "Give either 'element' or both 'x' and 'y'."


def _describe_click(args: dict) -> str:
    target = _click_target(args)
    how = ("Double-click" if args.get("double") else "Click") + (" (right button)" if args.get("button") == "right" else "")
    return f"{how} {target[1]}" if not isinstance(target, str) else f"{how}: {target}"


def looks_like_card_number(text: str) -> bool:
    """True if the text contains a 13-19 digit number that passes the Luhn
    check used by payment cards."""
    for match in re.finditer(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)", text):
        digits = [int(d) for d in match.group() if d.isdigit()]
        if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
            continue
        total = 0
        for i, d in enumerate(reversed(digits)):
            if i % 2 == 1:
                d = d * 2 - 9 if d * 2 > 9 else d * 2
            total += d
        if total % 10 == 0:
            return True
    return False


def _escalate_typing(args: dict, ctx: ToolContext):
    if looks_like_card_number(args.get("text", "")):
        return BLOCKED, "it looks like a payment card number, which JARVIS never enters"
    return None


@tool(
    name="type_text",
    description=(
        "Type text with the keyboard into whatever currently has the cursor. Click a text field first to put the "
        "cursor there. Never use this for passwords or payment details."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "press_enter": {"type": "boolean", "description": "Press Enter afterwards. Default false."},
        },
        "required": ["text"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="control",
    target_app=_front_app,
    escalate=_escalate_typing,
    describe=lambda a, c: f"Type this text{' and press Enter' if a.get('press_enter') else ''}:\n\n{a['text']}",
)
def type_text(args: dict, ctx: ToolContext) -> ToolResult:
    ctx.kill.check()
    try:
        _backend().type_text(args["text"])
        if args.get("press_enter"):
            _backend().press("enter")
    except DesktopUnavailable as exc:
        return _unavailable(exc)
    time.sleep(0.3)
    if args.get("press_enter"):
        return ToolResult(
            f"Typed {len(args['text'])} characters and pressed Enter. In a chat or message box, Enter SENDS: the "
            "message has gone and the box is now empty, which is normal. Do not type it again."
        )
    return ToolResult(f"Typed {len(args['text'])} characters.")


@tool(
    name="press_keys",
    description=(
        "Press a key or a key combination, such as 'enter', 'tab', 'esc', 'ctrl+s', 'alt+tab', 'ctrl+shift+t', "
        "'win+d', 'f5', 'down'. One combination per call."
    ),
    input_schema={
        "type": "object",
        "properties": {"keys": {"type": "string"}},
        "required": ["keys"],
        "additionalProperties": False,
    },
    tier=AUTO,
    kind="control",
    target_app=_front_app,
    describe=lambda a, c: f"Press {a['keys']}",
)
def press_keys(args: dict, ctx: ToolContext) -> ToolResult:
    try:
        to_send_keys(args["keys"])  # validate before touching the keyboard
    except ValueError as exc:
        return ToolResult(str(exc), is_error=True)
    ctx.kill.check()
    try:
        _backend().press(args["keys"])
    except DesktopUnavailable as exc:
        return _unavailable(exc)
    time.sleep(0.3)
    return ToolResult(f"Pressed {args['keys']}.")


# ----------------------------------------------- key names (pure, testable)

_MODIFIERS = {"ctrl": "^", "control": "^", "alt": "%", "shift": "+"}
_KEYS = {
    "enter": "{ENTER}", "return": "{ENTER}", "tab": "{TAB}", "esc": "{ESC}", "escape": "{ESC}",
    "space": "{SPACE}", "backspace": "{BACKSPACE}", "delete": "{DELETE}", "del": "{DELETE}",
    "insert": "{INSERT}", "home": "{HOME}", "end": "{END}", "pageup": "{PGUP}", "pgup": "{PGUP}",
    "pagedown": "{PGDN}", "pgdn": "{PGDN}", "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
    "printscreen": "{PRTSC}", "capslock": "{CAPSLOCK}",
}
_KEYS.update({f"f{n}": f"{{F{n}}}" for n in range(1, 13)})


def escape_text(text: str) -> str:
    """Make ordinary text safe for pywinauto's send_keys, where + ^ % ~ ( )
    { } [ ] have special meanings."""
    return "".join("{" + ch + "}" if ch in "+^%~(){}[]" else ch for ch in text)


def to_send_keys(combo: str) -> str:
    """'ctrl+shift+s' -> '^+s'; 'win+d' -> '{VK_LWIN down}d{VK_LWIN up}'."""
    parts = [p.strip().lower() for p in combo.replace(" ", "").split("+")] if combo.strip() != "+" else ["+"]
    if combo.strip().endswith("++"):  # e.g. ctrl++ (zoom in)
        parts = [p for p in parts if p] + ["+"]
    if not parts or any(p == "" for p in parts):
        raise ValueError(f"Could not understand the key combination {combo!r}.")
    *modifiers, key = parts
    prefix, wrap_win = "", False
    for m in modifiers:
        if m in ("win", "windows", "super"):
            wrap_win = True
        elif m in _MODIFIERS:
            prefix += _MODIFIERS[m]
        else:
            raise ValueError(f"{m!r} is not a modifier key. Use ctrl, alt, shift or win.")
    if key in ("win", "windows", "super"):
        return prefix + "{VK_LWIN}"
    if key in _KEYS:
        body = _KEYS[key]
    elif len(key) == 1:
        body = escape_text(key)
    else:
        raise ValueError(f"{key!r} is not a key name JARVIS knows.")
    return f"{{VK_LWIN down}}{prefix}{body}{{VK_LWIN up}}" if wrap_win else prefix + body


# ------------------------------------------------------- Windows backend

_INTERESTING = {
    "Button", "Edit", "Document", "Text", "MenuItem", "ListItem", "Hyperlink", "TabItem", "CheckBox",
    "ComboBox", "RadioButton", "TreeItem", "DataItem", "Menu", "SplitButton", "Slider", "Header", "HeaderItem",
}
_HAS_VALUE = {"Edit", "Document", "ComboBox"}
_UIA_VALUE_PROPERTY = 30045  # UI Automation's id for "the text in this field"


class WindowsBackend:
    """Everything that talks to Windows, via the pywinauto library."""

    def __init__(self):
        self.last_app: str | None = None  # the app of the latest snapshot
        try:
            import pywinauto  # noqa: F401
        except ImportError:
            raise DesktopUnavailable(
                'Screen reading and control need one more library. Run:  pip install -e ".[desktop]"'
            ) from None

    def _desktop(self):
        from pywinauto import Desktop

        return Desktop(backend="uia")

    def _visible_windows(self):
        result = []
        for w in self._desktop().windows():
            try:
                if w.is_visible() and w.window_text().strip():
                    result.append(w)
            except Exception:
                continue  # a window that closed while we were looking
        return result

    def _foreground_handle(self) -> int:
        import ctypes

        return ctypes.windll.user32.GetForegroundWindow()

    def _find(self, title: str | None):
        windows = self._visible_windows()
        if not title:
            handle = self._foreground_handle()
            for w in windows:
                if w.handle == handle:
                    return w
            if windows:
                return windows[0]
            raise DesktopUnavailable("No window is open.")
        wanted = title.lower()
        matches = [w for w in windows if wanted in w.window_text().lower()]
        if not matches:
            names = ", ".join(f'"{w.window_text()}"' for w in windows[:12])
            raise DesktopUnavailable(f"No open window has {title!r} in its title. Open windows: {names}")
        return min(matches, key=lambda w: len(w.window_text()))

    def _app_of(self, window) -> str | None:
        """A name for the program a window belongs to, e.g. 'WhatsApp.exe'.
        Store apps all run inside one host program, so for those the
        window's title is added: 'ApplicationFrameHost.exe|Calculator'."""
        try:
            import psutil

            name = psutil.Process(window.process_id()).name()
        except Exception:
            return None
        if name.lower() == "applicationframehost.exe":
            return f"{name}|{window.window_text().strip()}"
        return name

    def front_app(self) -> str | None:
        try:
            return self._app_of(self._find(None))
        except DesktopUnavailable:
            return None

    def windows(self) -> list[str]:
        windows = self._visible_windows()
        handle = self._foreground_handle()
        windows.sort(key=lambda w: w.handle != handle)  # the one in front first
        return [w.window_text() for w in windows]

    def snapshot(self, title: str | None) -> tuple[str, list[Element]]:
        window = self._find(title)
        self.last_app = self._app_of(window)
        info = window.element_info
        walker = info.iter_descendants() if hasattr(info, "iter_descendants") else iter(info.descendants())
        elements: list[Element] = []
        deadline = time.monotonic() + 8  # huge windows (web pages) must not hang JARVIS
        for item in walker:
            if time.monotonic() > deadline or len(elements) >= MAX_ELEMENTS * 2:
                break
            try:
                role = item.control_type or ""
                if role not in _INTERESTING or not item.visible:
                    continue
                r = item.rectangle
                if r.right - r.left <= 0 or r.bottom - r.top <= 0:
                    continue
                name = (item.name or "").strip()
                value = ""
                if role in _HAS_VALUE:
                    try:
                        value = str(item.element.GetCurrentPropertyValue(_UIA_VALUE_PROPERTY) or "")
                    except Exception:
                        value = ""
                if not name and not value and role in ("Text", "Menu", "Header"):
                    continue
                elements.append(Element(role, name, value, (r.left, r.top, r.right, r.bottom), bool(item.enabled)))
            except Exception:
                continue  # elements vanish while a window redraws
        return window.window_text(), elements

    def focus(self, title: str) -> str:
        window = self._find(title)
        try:
            if window.is_minimized():
                window.restore()
            window.set_focus()
        except Exception as exc:
            raise DesktopUnavailable(f"Could not bring that window to the front: {exc}") from None
        return window.window_text()

    def click(self, x: int, y: int, button: str, double: bool) -> None:
        from pywinauto import mouse

        if double:
            mouse.double_click(button=button, coords=(x, y))
        else:
            mouse.click(button=button, coords=(x, y))

    def type_text(self, text: str) -> None:
        from pywinauto import keyboard

        keyboard.send_keys(escape_text(text), with_spaces=True, with_tabs=True, with_newlines=True, pause=0.01)

    def press(self, combo: str) -> None:
        from pywinauto import keyboard

        keyboard.send_keys(to_send_keys(combo), pause=0.05)
