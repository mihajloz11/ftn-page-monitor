param(
    [switch]$TestNotification,
    [switch]$TestEmail
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$MonitorScript = Join-Path $ScriptDir "monitor_site.py"
$ConfigPath = Join-Path $ScriptDir "config.json"

$PythonCandidates = @(
    "python",
    "py",
    "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
)

$Python = $null
foreach ($Candidate in $PythonCandidates) {
    $Command = Get-Command $Candidate -ErrorAction SilentlyContinue
    if ($Command) {
        $Python = $Command.Source
        break
    }
}

if (-not $Python) {
    throw "Python nije pronadjen. Instaliraj Python ili pokreni iz Codex okruzenja koje ima bundlovani Python."
}

if (-not (Test-Path $ConfigPath)) {
    throw "Nedostaje config.json. Kopiraj config.example.json u config.json i popuni email podesavanja."
}

$Args = @($MonitorScript, "--config", $ConfigPath)
if ($TestNotification -or $TestEmail) {
    $Args += "--test-notification"
}

& $Python @Args
