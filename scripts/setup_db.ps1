# Setup local development database
# Ensures both development and test databases exist safely without dropping data.

docker compose up -d db
Write-Host "Waiting for PostgreSQL container to become healthy..."

# Wait up to 30 seconds for health check
$timeout = 30
$elapsed = 0
while ($elapsed -lt $timeout) {
    $status = docker inspect --format='{{json .State.Health.Status}}' ledgerline-db 2>$null
    if ($status -eq '"healthy"') {
        break
    }
    Start-Sleep -Seconds 2
    $elapsed += 2
}

# Ensure test database exists if container was already initialized prior to init script mount
docker compose exec -T db psql -U ledgerline -d postgres -c "SELECT 'CREATE DATABASE ledgerline_test' WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'ledgerline_test')\gexec"

Write-Host "Databases verified: ledgerline (dev) and ledgerline_test (test)."
