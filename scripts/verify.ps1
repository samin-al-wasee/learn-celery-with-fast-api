#Requires -Version 7
<#
.SYNOPSIS
    VERIFY gate of the Loop Engineer (LOOP.md). Exit 0 = green, 1 = red.
.EXAMPLE
    .\scripts\verify.ps1                          # full gate
    .\scripts\verify.ps1 -Quick                   # compile + import only
    .\scripts\verify.ps1 -RequireDocs             # DOCUMENT exit gate
    .\scripts\verify.ps1 -Observe observe_stampede.py
#>
[CmdletBinding()]
param(
    [switch]$Quick,
    [switch]$RequireDocs,
    [string]$Observe,
    [string]$Base = "main",
    [int]$MaxFiles = 9
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Push-Location $root
$failures = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

function Step([string]$name, [scriptblock]$body) {
    Write-Host "-> $name" -ForegroundColor Cyan
    try { & $body } catch { $failures.Add("${name}: $($_.Exception.Message)") }
}

function Invoke-Checked([string]$exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "'$exe $($argv -join ' ')' exited $LASTEXITCODE" }
}

$env:PYTHONPATH = $root
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

try {
    Step "compile app/ + scripts/" { Invoke-Checked $python @("-m", "compileall", "-q", "app", "scripts") }
    Step "import app.main" { Invoke-Checked $python @("-c", "import app.main") }

    if (-not $Quick) {
        $changed = @(
            git diff --name-only "$Base...HEAD" 2>$null
            git diff --name-only HEAD 2>$null
            git ls-files --others --exclude-standard
        ) | Where-Object { $_ } | Sort-Object -Unique

        Step "no secrets tracked" {
            $leaked = git ls-files | Where-Object { $_ -match '(^|/)\.env($|\.)' -and $_ -notmatch '\.env\.example$' }
            if ($leaked) { throw "tracked env file(s): $($leaked -join ', ')" }
        }

        Step "Bruno collection in lockstep with routes" {
            $routes = $changed | Where-Object { $_ -like "app/api/routes/*" }
            $bruno = $changed | Where-Object { $_ -like "api/collection/*" }
            if ($routes -and -not $bruno) { throw "routes changed ($($routes -join ', ')) but no api/collection/*.bru changed" }
        }

        Step "scope" {
            if ($changed.Count -gt $MaxFiles) {
                $warnings.Add("$($changed.Count) files changed vs $Base -- split into commits of <10 files (AGENTS.md section 7)")
            }
        }

        if (Test-Path "tests") {
            Step "pytest" { Invoke-Checked $python @("-m", "pytest", "-q") }
        }

        if ($Observe) {
            Step "observe: $Observe" { Invoke-Checked $python @((Join-Path "scripts" $Observe)) }
        }

        if ($RequireDocs) {
            Step "docs updated (LEARNING.md + ROADMAP.md)" {
                $missing = @("LEARNING.md", "ROADMAP.md") | Where-Object { $_ -notin $changed }
                if ($missing) { throw "not in diff: $($missing -join ', ')" }
            }
        }

        Write-Host "`nChanged vs ${Base}: $($changed.Count) file(s)"
        $changed | ForEach-Object { Write-Host "   $_" }
    }
}
finally {
    Pop-Location
}

$warnings | ForEach-Object { Write-Host "WARN $_" -ForegroundColor Yellow }
if ($failures.Count) {
    $failures | ForEach-Object { Write-Host "FAIL $_" -ForegroundColor Red }
    Write-Host "VERIFY: RED" -ForegroundColor Red
    exit 1
}
Write-Host "VERIFY: GREEN" -ForegroundColor Green
exit 0
