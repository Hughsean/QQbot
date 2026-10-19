# Go migration branch: development artifact, not a completed production replacement.
FROM golang:1.27.2-bookworm@sha256:5cf287a799e6b94384bad13d16b14904c531f51ba65792237e122ce42b392f61 AS build
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY cmd/ ./cmd/
COPY internal/ ./internal/
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /qq-time-agent ./cmd/qq-time-agent

FROM build AS verify
COPY tests/ ./tests/
COPY docs/go-legacy-test-inventory.json ./docs/go-legacy-test-inventory.json
COPY ops/ ./ops/
COPY .github/ ./.github/
CMD ["go", "test", "-race", "-tags=integration", "./..."]

FROM scratch AS runtime
COPY --from=build /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/ca-certificates.crt
COPY --from=build /qq-time-agent /qq-time-agent
USER 10001:10001
WORKDIR /app
ENTRYPOINT ["/qq-time-agent"]
CMD ["web"]
