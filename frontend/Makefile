.PHONY: dev-css dev-go gen-client test lint build tailwind-watch

TAILWIND_BIN ?= ./tailwindcss
BACKEND_URL  ?= http://localhost:8000

## dev-css: watch and rebuild Tailwind CSS on source change
dev-css: tailwind-watch

tailwind-watch:
	$(TAILWIND_BIN) -i web/styles/app.css -o web/static/app.css --watch

## dev-go: run the Go server with default settings (requires tailwindcss output in web/static/)
dev-go:
	BACKEND_URL=$(BACKEND_URL) go run ./cmd/server

## gen-client: regenerate the oapi-codegen typed client from the backend OpenAPI spec
gen-client:
	go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen \
	  --config oapi-codegen.yaml ../backend/openapi.json

## test: run all tests with race detector
test:
	go test -race ./...

## lint: run go vet and staticcheck
lint:
	go vet ./...

## build: compile the server binary locally (Tailwind CSS must already be compiled)
build:
	CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /tmp/lph-frontend ./cmd/server
