<#
  Nipun.AI — Windows dev helper (make-equivalent; `make` isn't available here).

  Usage (from anywhere):
    .\dev.ps1 infra        # start Postgres, Redis, Qdrant, Elasticsearch
    .\dev.ps1 infra-full   # + Prometheus + Grafana
    .\dev.ps1 down         # stop all containers
    .\dev.ps1 ps | logs    # status / tail logs
    .\dev.ps1 migrate      # apply DB migrations (run once before first backend start)
    .\dev.ps1 backend      # run the API (uvicorn, reload)
    .\dev.ps1 worker       # run the Celery worker (Windows: solo pool)
    .\dev.ps1 beat         # run the Celery beat scheduler
    .\dev.ps1 ingest [legal]   # ingest one domain, or all domains if omitted
    .\dev.ps1 test [args]  # run the backend test suite
    .\dev.ps1 up           # infra + migrate + backend, in order

  All docker compose commands read variables from backend/.env (single source of truth).
#>
param(
  [Parameter(Position = 0)][string]$cmd = "help",
  [Parameter(ValueFromRemainingArguments = $true)]$rest
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot   # repo root — so docker-compose.yml, backend/.env, ./data all resolve

function Compose { docker compose --env-file backend/.env @args }
function InBackend([scriptblock]$block) { Push-Location backend; try { & $block } finally { Pop-Location } }

switch ($cmd.ToLower()) {
  "infra" {
    Compose up -d postgres redis qdrant elasticsearch
    Write-Host "OK - Postgres:5432  Redis:6379  Qdrant:6333  ES:9200" -ForegroundColor Green
    Write-Host "Next:  .\dev.ps1 migrate   then   .\dev.ps1 backend"
  }
  "infra-full" { Compose up -d }
  "down"       { Compose down }
  "logs"       { Compose logs -f }
  "ps"         { Compose ps }

  "migrate"    { InBackend { uv run python -m src.db.migrate } }
  "backend"    { InBackend { uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir src } }
  "worker"     { InBackend { uv run celery -A src.worker.celery_app worker --loglevel=info --pool=solo --queues=ingestion.document,ingestion.realtime } }
  "beat"       { InBackend { uv run celery -A src.worker.celery_app beat --loglevel=info } }
  "ingest" {
    $arg = if ($rest) { @("--domain") + $rest } else { @("--all") }
    InBackend { uv run python -m src.ingestion.run @arg }
  }
  "test"       { InBackend { uv run pytest @rest } }

  "up" {
    Compose up -d postgres redis qdrant elasticsearch
    Write-Host "Waiting 8s for databases to accept connections..." -ForegroundColor Yellow
    Start-Sleep -Seconds 8
    InBackend { uv run python -m src.db.migrate }
    InBackend { uv run uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir src }
  }

  default {
    Write-Host "Usage: .\dev.ps1 {infra|infra-full|down|logs|ps|migrate|backend|worker|beat|ingest|test|up}"
  }
}
