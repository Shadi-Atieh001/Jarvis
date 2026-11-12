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


def powershell_script(pythonw: Path, workdir: Path, icon: Path) -> str:
    """The PowerShell that creates both shortcuts. Windows has no simpler
    built-in way to make a .lnk file."""

    def quote(value) -> str:  # PowerShell single-quoted string
        return "'" + str(value).replace("'", "''") + "'"

    return "\n".join(
        [
            "$shell = New-Object -ComObject WScript.Shell",
            "$folders = @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))",
            "foreach ($folder in $folders) {",
            "  $link = $shell.CreateShortcut((Join-Path $folder 'JARVIS.lnk'))",
            f"  $link.TargetPath = {quote(pythonw)}",
            "  $link.Arguments = '-m jarvis'",
            f"  $link.WorkingDirectory = {quote(workdir)}",
            f"  $link.IconLocation = {quote(icon)}",
            "  $link.Description = 'JARVIS personal assistant'",
            "  $link.Save()",
            "  Write-Output $link.FullName",
            "}",
        ]
    )


def install(out=print) -> int:
    if sys.platform != "win32":
        out("Shortcuts can only be installed on Windows.")
        return 1
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        out(f"Could not find {pythonw}. Run this command with the Python inside the .venv folder.")
        return 1
    script = powershell_script(pythonw, REPO_ROOT, ICON)
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        out(f"Windows refused to create the shortcut:\n{result.stderr.strip()}")
        return 1
    out("Created:\n" + result.stdout.strip())
    out('Double-click JARVIS on the desktop, or press the Windows key and type "Jarvis".')
    return 0
