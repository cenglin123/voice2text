param(
    [Parameter(Mandatory=$true)][string]$Archive,
    [Parameter(Mandatory=$true)][string]$InstallDir,
    [Parameter(Mandatory=$true)][int]$ProcessId,
    [Parameter(Mandatory=$true)][string]$Version,
    [switch]$NoRestart,
    [switch]$KeepScript
)

$ErrorActionPreference = "Stop"
$updateRoot = Join-Path $env:LOCALAPPDATA "voice2text\updates"
$staging = Join-Path $updateRoot ("stage-" + [Guid]::NewGuid().ToString("N"))
$log = Join-Path $updateRoot "update.log"

function Write-UpdateLog([string]$Message) {
    New-Item -ItemType Directory -Force -Path $updateRoot | Out-Null
    Add-Content -LiteralPath $log -Encoding UTF8 -Value ((Get-Date -Format s) + " " + $Message)
}

try {
    New-Item -ItemType Directory -Force -Path $updateRoot | Out-Null
    $deadline = (Get-Date).AddSeconds(60)
    while (Get-Process -Id $ProcessId -ErrorAction SilentlyContinue) {
        if ((Get-Date) -gt $deadline) { throw "Timed out waiting for the previous version to exit" }
        Start-Sleep -Milliseconds 200
    }

    Expand-Archive -LiteralPath $Archive -DestinationPath $staging -Force
    $source = Join-Path $staging ("voice2text-v" + $Version + "-windows-x64")
    if (-not (Test-Path -LiteralPath (Join-Path $source "offline-bundle.txt"))) {
        throw "Invalid update archive layout"
    }

    $config = Join-Path $InstallDir "config.json"
    if (Test-Path -LiteralPath $config) {
        Copy-Item -LiteralPath $config -Destination (Join-Path $source "config.json") -Force
    }
    $llm = Join-Path $InstallDir "models\llm"
    if (Test-Path -LiteralPath $llm) {
        $targetModels = Join-Path $source "models"
        New-Item -ItemType Directory -Force -Path $targetModels | Out-Null
        Copy-Item -LiteralPath $llm -Destination $targetModels -Recurse -Force
    }

    Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $InstallDir -Recurse -Force
    }
    Write-UpdateLog ("updated to v" + $Version)
    if (-not $NoRestart) {
        Start-Process -FilePath (Join-Path $InstallDir "run.bat") -WorkingDirectory $InstallDir
    }
    Remove-Item -LiteralPath $Archive -Force -ErrorAction SilentlyContinue
} catch {
    Write-UpdateLog ("FAILED: " + $_.Exception.Message)
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show(
        "The update failed. Existing files and settings were kept.`n`n" + $_.Exception.Message + "`n`nLog: " + $log,
        "voice2text update failed", "OK", "Error"
    ) | Out-Null
} finally {
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not $KeepScript) {
        Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
    }
}
