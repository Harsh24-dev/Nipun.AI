<#
  Nipun.AI - one-command dev launcher.

  Starts everything you need for local development:
    1. Infra containers (Postgres, Redis, Qdrant, Elasticsearch) via docker compose
    2. Backend API  (FastAPI / uvicorn, hot-reload) on http://localhost:8000
    3. Frontend     (Vite dev server, hot-reload)    on http://localhost:5173

  WHERE the two servers run:
    - Inside VS Code  -> use the integrated terminals via the "Run App" task:
                         press Ctrl+Shift+B  (this script points you there).
    - Anywhere else   -> each server opens in its own PowerShell window.

  Usage (from anywhere):
    .\run-app.ps1              # infra + migrate + backend + frontend
    .\run-app.ps1 -External    # force PowerShell windows even inside VS Code
    .\run-app.ps1 -NoInfra     # skip docker (use when infra is already running)
    .\run-app.ps1 -SkipMigrate # skip DB migrations (they run by default, needed on a fresh DB)

  Notes:
    - Docker compose reads its variables from backend/.env (single source of truth).
    - 'uv' is auto-located: PATH first, then the repo's env\Scripts\uv.exe.
#>
[CmdletBinding()]
param(
  [switch]$NoInfra,
  [switch]$SkipMigrate,
  [switch]$External
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

# --- Locate uv (PATH, else the repo's env venv) ---------------------------------
$uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
if (-not $uv) { $uv = Join-Path $root "env\Scripts\uv.exe" }
if (-not (Test-Path $uv)) {
  throw "Could not find 'uv'. Install it (pip install uv) or activate the 'env' venv, then retry."
}
Write-Host "Using uv: $uv" -ForegroundColor DarkGray

# --- Prefer VS Code integrated terminals when running inside VS Code ------------
# A CLI script cannot open VS Code integrated terminals directly; that is what the
# .vscode/tasks.json "Run App" task is for. So inside VS Code we delegate to it.
$inVSCode = ($env:TERM_PROGRAM -eq 'vscode') -and [bool](Get-Command code -ErrorAction SilentlyContinue)
if ($inVSCode -and -not $External) {
  Write-Host "`nVS Code detected." -ForegroundColor Green
  Write-Host "Run backend + frontend in VS Code's integrated terminals with the 'Run App' task:" -ForegroundColor Cyan
  Write-Host "    Press  Ctrl+Shift+B" -ForegroundColor White
  Write-Host "    (or:  Terminal > Run Task... > Run App)"
  Write-Host "That task starts infra, migrates, then opens Backend + Frontend terminals."
  Write-Host "`nPrefer separate PowerShell windows instead?  ->  .\run-app.ps1 -External" -ForegroundColor DarkGray
  return
}

# --- 1. Infra -------------------------------------------------------------------
if (-not $NoInfra) {
  Write-Host "`n[1/3] Starting infra (Postgres, Redis, Qdrant, Elasticsearch)..." -ForegroundColor Cyan
  docker compose --env-file backend/.env up -d postgres redis qdrant elasticsearch
  if ($LASTEXITCODE -ne 0) { throw "docker compose failed - is Docker Desktop running?" }
  Write-Host "Waiting 8s for databases to accept connections..." -ForegroundColor Yellow
  Start-Sleep -Seconds 8
} else {
  Write-Host "`n[1/3] Skipping infra (-NoInfra)." -ForegroundColor DarkGray
}

# --- 2. Migrations (default on; required on a fresh DB, no-op once applied) ------
if (-not $SkipMigrate) {
  Write-Host "`n[migrate] Applying DB migrations..." -ForegroundColor Cyan
  Push-Location (Join-Path $root "backend")
  try { & $uv run python -m src.db.migrate; if ($LASTEXITCODE -ne 0) { throw "migration failed" } }
  finally { Pop-Location }
  Write-Host "Migrations applied." -ForegroundColor DarkGray
}

# --- 3. Backend (own window) ----------------------------------------------------
Write-Host "`n[2/3] Launching backend  -> http://localhost:8000 (new window)" -ForegroundColor Cyan
$backendCmd = "Set-Location '$root\backend'; " +
  "& '$uv' run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir src --log-level debug"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $backendCmd | Out-Null

# --- 4. Frontend (own window) ---------------------------------------------------
Write-Host "[3/3] Launching frontend -> http://localhost:5173 (new window)" -ForegroundColor Cyan
$frontendCmd = "Set-Location '$root\frontend'; npm run dev"
Start-Process powershell -ArgumentList "-NoExit", "-Command", $frontendCmd | Out-Null

Write-Host "`nAll started. Two new windows opened (backend + frontend)." -ForegroundColor Green
Write-Host "  Backend :  http://localhost:8000        (docs: http://localhost:8000/docs)"
Write-Host "  Frontend:  http://localhost:5173"
Write-Host "  Stop a server by closing its window or pressing Ctrl+C in it."
Write-Host "  Stop infra with:  docker compose --env-file backend/.env down"
