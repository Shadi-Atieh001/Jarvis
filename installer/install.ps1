# Installs JARVIS for the current Windows user, or updates it if it is
# already installed. Run by Install-JARVIS.bat; safe to run again.
#
# What it does, in order:
#   1. Installs Python 3.14 and Git with winget, if they are missing.
#   2. Downloads JARVIS into  <your user folder>\Jarvis  (or updates it).
#   3. Creates JARVIS's own Python environment there and installs its libraries.
#   4. Downloads the speech and memory models (about 280 MB).
#   5. Adds a JARVIS icon to the desktop and Start menu, and starts JARVIS.
#
# To remove JARVIS later, see "Uninstalling" in the README.

$Repository = "https://github.com/Shadi-Atieh001/Jarvis.git"
$Folder = Join-Path $HOME "Jarvis"

function Say($text) { Write-Host ""; Write-Host "== $text" -ForegroundColor Cyan }
function Have($command) { return [bool](Get-Command $command -ErrorAction SilentlyContinue) }
function Refresh-Path {
    # Pick up programs installed a moment ago without opening a new window.
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
}
function Check($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what did not succeed (exit code $LASTEXITCODE)." }
}
function Find-Python {
    # Returns the path of a Python 3.13 or 3.14, or $null. (3.15 is too new
    # for the speech libraries.)
    foreach ($version in @("3.14", "3.13")) {
        if (Have py) {
            $found = cmd /c "py -$version -c ""import sys; print(sys.executable)"" 2>nul"
            if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -First 1).Trim() }
        }
        $usual = Join-Path $env:LOCALAPPDATA ("Programs\Python\Python" + $version.Replace(".", "") + "\python.exe")
        if (Test-Path $usual) { return $usual }
    }
    return $null
}
function Find-Git {
    if (Have git) { return "git" }
    $usual = Join-Path $env:ProgramFiles "Git\cmd\git.exe"
    if (Test-Path $usual) { return $usual }
    return $null
}

try {
    Say "Checking what is already installed"
    $python = Find-Python
    $git = Find-Git
    if ((-not $python -or -not $git) -and -not (Have winget)) {
        throw "This installer uses 'winget', which is missing. Install 'App Installer' from the Microsoft Store, then run this again."
    }

    if (-not $python) {
        Say "Installing Python 3.14 (Windows may ask for permission)"
        winget install -e --id Python.Python.3.14 --scope user --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $python = Find-Python
        if (-not $python) { throw "Python was installed but cannot be found yet. Close this window and run the installer again." }
    }
    Write-Host "Python: $python"

    if (-not $git) {
        Say "Installing Git (Windows may ask for permission)"
        winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
        Refresh-Path
        $git = Find-Git
        if (-not $git) { throw "Git was installed but cannot be found yet. Close this window and run the installer again." }
    }
    Write-Host "Git: $git"

    if (Test-Path (Join-Path $Folder ".git")) {
        Say "JARVIS is already here; updating it"
        & $git -C $Folder pull --ff-only
        Check "Updating JARVIS"
    } elseif (Test-Path $Folder) {
        throw "A folder called $Folder already exists but is not JARVIS. Rename or remove it, then run this again."
    } else {
        Say "Downloading JARVIS to $Folder"
        & $git clone $Repository $Folder
        Check "Downloading JARVIS"
    }

    Set-Location $Folder
    $jarvisPython = Join-Path $Folder ".venv\Scripts\python.exe"
    if (-not (Test-Path $jarvisPython)) {
        Say "Creating JARVIS's own Python environment"
        & $python -m venv .venv
        Check "Creating the environment"
    }

    Say "Installing JARVIS's libraries (the longest step; several minutes)"
    & $jarvisPython -m pip install --disable-pip-version-check -e ".[desktop,memory,voice]"
    Check "Installing the libraries"

    Say "Downloading the speech and memory models (about 280 MB)"
    & $jarvisPython -m jarvis setup
    if ($LASTEXITCODE -ne 0) {
        Write-Host "The models could not be fully set up. JARVIS will still work by typing;" -ForegroundColor Yellow
        Write-Host "voice can be set up later with:  .venv\Scripts\python -m jarvis setup" -ForegroundColor Yellow
    }

    Say "Adding the JARVIS icon to your desktop and Start menu"
    & $jarvisPython -m jarvis install-shortcut
    if ($LASTEXITCODE -ne 0) { Write-Host "The icon could not be created; start JARVIS from $Folder instead." -ForegroundColor Yellow }

    Say "Starting JARVIS"
    Start-Process -FilePath (Join-Path $Folder ".venv\Scripts\pythonw.exe") -ArgumentList "-m", "jarvis" -WorkingDirectory $Folder

    Write-Host ""
    Write-Host "JARVIS is installed. A setup screen will ask for your name, your city and a model key." -ForegroundColor Green
    Write-Host "From now on, start it with the JARVIS icon on your desktop." -ForegroundColor Green
}
catch {
    Write-Host ""
    Write-Host "The installation stopped: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "Nothing harmful has happened. Fix the problem above and run the installer again." -ForegroundColor Red
}
Write-Host ""
Read-Host "Press Enter to close this window"
