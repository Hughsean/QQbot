param(
    [string]$Destination = "",
    [switch]$IncludeImages
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed: $File" }
}

if (-not $Destination) { $Destination = Join-Path $ProjectRoot "qq-time-agent-migration.tar.gz" }
$destinationPath = [System.IO.Path]::GetFullPath($Destination)
$stage = Join-Path ([System.IO.Path]::GetTempPath()) ("qq-time-agent-bundle-" + [guid]::NewGuid())
New-Item -ItemType Directory -Force -Path (Join-Path $stage "data"), (Join-Path $stage "images") | Out-Null
try {
    $assetsVolume = (docker volume ls -q -f label=com.docker.compose.volume=qq_time_agent_assets | Select-Object -First 1).Trim()
    $ollamaVolume = (docker volume ls -q -f label=com.docker.compose.volume=qq_time_agent_ollama | Select-Object -First 1).Trim()
    if (-not $assetsVolume) { throw "qq_time_agent_assets volume was not found" }
    if (-not $ollamaVolume) { throw "qq_time_agent_ollama volume was not found; start Ollama and pull the model first" }

    Write-Output "Exporting PostgreSQL dump."
    docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > (Join-Path $stage "data/database.dump")
    if ($LASTEXITCODE -ne 0) { throw "PostgreSQL dump failed" }

    Write-Output "Exporting assets and Ollama model volumes."
    Invoke-Checked docker @("run", "--rm", "-v", "${assetsVolume}:/data:ro", "-v", "${stage}:/out", "debian:bookworm-slim", "tar", "-C", "/data", "-cf", "/out/data/assets.tar", ".")
    Invoke-Checked docker @("run", "--rm", "-v", "${ollamaVolume}:/data:ro", "-v", "${stage}:/out", "debian:bookworm-slim", "tar", "-C", "/data", "-cf", "/out/data/ollama-model.tar", ".")

    if ($IncludeImages) {
        Write-Output "Saving application, PostgreSQL and Ollama images."
        Invoke-Checked docker @("save", "-o", (Join-Path $stage "images/images.tar"), "qq-time-agent:local", "pgvector/pgvector:0.8.1-pg17", "ollama/ollama")
    }

    $files = @("compose.yaml", "compose.gpu.yaml", "Dockerfile", ".dockerignore", ".env.example", ".python-version", "pyproject.toml", "uv.lock", "alembic.ini", "alembic", "src", "docs", "ops", "start.sh", "MIGRATION.md")
    foreach ($file in $files) {
        $source = Join-Path $ProjectRoot $file
        if (Test-Path -LiteralPath $source) { Copy-Item -LiteralPath $source -Destination (Join-Path $stage $file) -Recurse -Force }
    }
    Get-ChildItem -LiteralPath $stage -Recurse -Force -Directory |
        Where-Object { $_.Name -in @("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache") } |
        Sort-Object FullName -Descending |
        Remove-Item -Recurse -Force
    $manifest = [ordered]@{
        format = 1
        created_at_utc = [DateTime]::UtcNow.ToString("o")
        architecture = "linux/amd64"
        database_dump = "data/database.dump"
        assets_archive = "data/assets.tar"
        ollama_model_archive = "data/ollama-model.tar"
        includes_images = $IncludeImages.IsPresent
        required_secret_inputs = @("DATABASE_PASSWORD", "CREDENTIAL_ENCRYPTION_KEY", "APP_SIGNING_KEY", "QQ_BOT_SECRET", "DEEPSEEK_API_KEY")
        required_model = "qwen3-embedding:4b"
        embedding_dimensions = 1024
        source_commit = (git rev-parse HEAD).Trim()
        source_tree_dirty = [bool](git status --porcelain)
    }
    $manifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $stage "manifest.json") -Encoding utf8NoBOM
    $hashes = Get-ChildItem -File -Recurse $stage | ForEach-Object {
        $relative = $_.FullName.Substring($stage.Length + 1).Replace("\", "/")
        "$((Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash)  $relative"
    }
    $hashes | Set-Content -LiteralPath (Join-Path $stage "SHA256SUMS") -Encoding ascii
    $parent = Split-Path -Parent $destinationPath
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if (Test-Path -LiteralPath $destinationPath) { Remove-Item -LiteralPath $destinationPath -Force }
    tar -czf $destinationPath -C $stage .
    if ($LASTEXITCODE -ne 0) { throw "Creating migration archive failed" }
    Write-Output "Migration bundle created: $destinationPath"
} finally {
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
}
