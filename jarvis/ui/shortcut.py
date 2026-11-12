"""python -m jarvis install-shortcut

Adds a JARVIS shortcut to the desktop and the Start menu, so it can be
started with a double-click and found by typing "Jarvis" in Start. The
shortcut runs JARVIS with pythonw.exe, which is Python without the black
terminal window. Anything JARVIS would have printed goes to
~/.jarvis/jarvis.log instead.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from jarvis.core.config import REPO_ROOT

ICON = Path(__file__).parent / "web" / "jarvis.ico"


def _quote(value) -> str:  # a PowerShell single-quoted string
    return "'" + str(value).replace("'", "''") + "'"


def powershell_script(pythonw: Path, workdir: Path, icon: Path, folders=("Desktop", "Programs"), arguments: str = "-m jarvis") -> str:
    """The PowerShell that creates the shortcuts. Windows has no simpler
    built-in way to make a .lnk file. 'Programs' is the Start menu;
    'Startup' is the folder of things Windows starts when you sign in."""
    wanted = ", ".join(f"[Environment]::GetFolderPath({_quote(f)})" for f in folders)
    return "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            f"$folders = @({wanted})",
            "foreach ($folder in $folders) {",
            "  $link = $shell.CreateShortcut((Join-Path $folder 'JARVIS.lnk'))",
            f"  $link.TargetPath = {_quote(pythonw)}",
            f"  $link.Arguments = {_quote(arguments)}",
            f"  $link.WorkingDirectory = {_quote(workdir)}",
            f"  $link.IconLocation = {_quote(icon)}",
            "  $link.Description = 'JARVIS personal assistant'",
            "  $link.Save()",
            "  Write-Output $link.FullName",
            "}",
        ]
    )


def _run(script: str):
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script], capture_output=True, text=True
    )


def autostart(turn_on: bool, out=print) -> int:
    """Start JARVIS, hidden in the tray, whenever you sign in to Windows."""
    if sys.platform != "win32":
        out("This only works on Windows.")
        return 1
    if turn_on:
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        result = _run(powershell_script(pythonw, REPO_ROOT, ICON, folders=("Startup",), arguments="-m jarvis --tray"))
        if result.returncode != 0:
            out(f"Windows refused:\n{result.stderr.strip()}")
            return 1
        out("JARVIS will now start in the tray (by the clock) each time you sign in to Windows.")
    else:
        _run("Remove-Item -ErrorAction SilentlyContinue (Join-Path ([Environment]::GetFolderPath('Startup')) 'JARVIS.lnk')")
        out("JARVIS will no longer start with Windows.")
    return 0


def install(out=print) -> int:
    if sys.platform != "win32":
        out("Shortcuts can only be installed on Windows.")
        return 1
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        out(f"Could not find {pythonw}. Run this command with the Python inside the .venv folder.")
        return 1
    result = _run(powershell_script(pythonw, REPO_ROOT, ICON))
    if result.returncode != 0:
        out(f"Windows refused to create the shortcut:\n{result.stderr.strip()}")
        return 1
    out("Created:\n" + result.stdout.strip())
    out('Double-click JARVIS on the desktop, or press the Windows key and type "Jarvis".')
    return 0
