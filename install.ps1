# Compass bootstrap installer for Windows (PowerShell 5.1 or 7), run from a clone:
#
#   powershell -ExecutionPolicy Bypass -File .\install.ps1                      # asks its questions
#   powershell -ExecutionPolicy Bypass -File .\install.ps1 -Editable --yes --scope user --mode files
#
# It holds no logic of its own (IN-12): it makes sure uv is installed, installs
# the compass CLI from this folder with `uv tool install`, then runs
# `compass install` with every other argument. Its own options:
#   -Editable      install this checkout editable (changes under src/ apply at once)
#   -Repo <path>   the repository to set up (default: the current directory)
#   -YesUv         install uv without asking
# There is no param() block on purpose: arguments such as --yes reach
# `compass install` as they are, instead of being bound by PowerShell.

$ErrorActionPreference = "Stop"
$Source = $PSScriptRoot
$Editable = $false
$Repo = (Get-Location).Path
$YesUv = $false
$Rest = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    switch ($args[$i]) {
        "-Editable" { $Editable = $true }
        "-Repo" { $i++; $Repo = $args[$i] }
        "-YesUv" { $YesUv = $true }
        "--" { }
        default { $Rest += [string]$args[$i] }
    }
}

function Find-Uv {
    $cmd = Get-Command uv -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    foreach ($dir in @("$env:USERPROFILE\.local\bin", "$env:USERPROFILE\.cargo\bin")) {
        if (Test-Path "$dir\uv.exe") { return "$dir\uv.exe" }
    }
    return $null
}

$uv = Find-Uv
if (-not $uv) {
    if (-not $YesUv) {
        $answer = Read-Host "uv is not installed. Install it with uv's official installer? [Y/n]"
        if ($answer -and -not $answer.ToLower().StartsWith("y")) {
            Write-Host "uv is needed for the compass CLI; see https://docs.astral.sh/uv/"
            exit 1
        }
    }
    powershell -NoProfile -ExecutionPolicy ByPass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    $uv = Find-Uv
    if (-not $uv) { Write-Host "uv was installed but cannot be found; open a new terminal and run this again"; exit 1 }
}
Write-Host "uv: $uv"

$installArgs = @("tool", "install", "--force", "--compile-bytecode")
if ($Editable) { $installArgs += "--editable" }
$installArgs += $Source
& $uv @installArgs
if ($LASTEXITCODE -ne 0) { Write-Host "uv tool install failed"; exit 1 }

# uv's tool folder on PATH, for this session and (through update-shell) for new ones.
$bin = if ($env:UV_TOOL_BIN_DIR) { $env:UV_TOOL_BIN_DIR } else { "$env:USERPROFILE\.local\bin" }
if (-not (($env:PATH -split ";") -contains $bin)) {
    $env:PATH = "$bin;$env:PATH"
    & $uv tool update-shell | Out-Null
    Write-Host "Added $bin to PATH; open a new terminal (and restart your IDE) before starting Claude Code."
}

$compass = "$bin\compass.exe"
if (-not (Test-Path $compass)) { $compass = (Get-Command compass).Source }
& $compass -C $Repo install --skip-cli @Rest
exit $LASTEXITCODE
