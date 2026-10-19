# Go migration branch

This branch contains the Go foundation, account/credential modules, email authorization
adapters and the frozen PostgreSQL schema, not a
complete replacement for the existing application. Track G1–G10 in
`docs/32-go-migration.md`. The original implementation and tests remain at
`Main@c63eae17adf4fc2cf26c694ae8ba7e7f23c93470`; historical test scenarios are
listed in `docs/go-legacy-test-inventory.json`.

## Development

Use Go 1.27.2 and Go Modules. Run `go test ./...`, `go vet ./...`, and
`go build ./cmd/qq-time-agent`. Configuration is loaded only by Bootstrap. Do not
print or commit real `.env` values.

For synthetic integration tests, start the dedicated infrastructure:

```sh
docker compose --project-name qqtimeagent-go-test --env-file ops/go-test.settings -f compose.go-test.yaml up -d --wait
go test -tags=integration '-coverpkg=qqtimeagent/...' '-coverprofile=coverage.out' ./...
pwsh -File ops/Test-GoCoverage.ps1 -CoveragePath coverage.out
```

The default Compose project is `qq-time-agent-go-dev`, with separate Go development
volumes. Only the `development` profile starts the health Web process. The `migrate`
operation initializes empty databases; it refuses to adopt an unverified existing
Python database. Account modules and loopback HTTP contracts have passed local
tests. Both read-only probes are now owner-authorized: QQ Mail passed, while
Microsoft awaits the interactive browser callback;
see `docs/34-go-account-migration.md`. Their business HTTP routes are not yet
wired into the health-only process: source deletion and audit must use the real
modules as they migrate. Worker, business QQ processing, mail synchronization,
Agenda, RAG and To Do remain scheduled migration work. Do not mount production volumes into this
stack or deploy it as the production replacement.

## HP deployment retained in stopped state

On 2026-10-19, at the owner's request, the existing Python Web/Worker/QQ containers
in the remote `qq-time-agent-bundle` project were stopped. Containers, the original
image, all volumes and their `unless-stopped` restart policy were retained.
PostgreSQL and Ollama stayed running. No Go service was deployed to HP.

The retained containers can be restored with an explicit `docker start` of
`qq-time-agent-bundle-web-1`, `qq-time-agent-bundle-worker-1` and
`qq-time-agent-bundle-qq-1`. Restoring them is a separate operational decision; do
not run old and new consumers against the same database.
