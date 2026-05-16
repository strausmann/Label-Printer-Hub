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

## gen-client: regenerate the typed client from the committed OpenAPI snapshot.
## The snapshot (internal/api/openapi.snapshot.json) is the canonical source;
## refresh it first with: make refresh-snapshot
gen-client:
	go run github.com/oapi-codegen/oapi-codegen/v2/cmd/oapi-codegen \
	  --config oapi-codegen.yaml internal/api/openapi.snapshot.json

## refresh-snapshot: download a fresh OpenAPI spec from the backend and save it.
## Requires the backend to be running at BACKEND_URL.
refresh-snapshot:
	curl -fsSL $(BACKEND_URL)/openapi.json | python3 -c "\
import sys,json; s=json.load(sys.stdin);\
[s.get('paths',{}).get(p,{}).get(m,{}) for p in list(s.get('paths',{}).keys()) for m in list(s.get('paths',{}).get(p,{}).keys())]; \
print(json.dumps(s,indent=2))" > internal/api/openapi.snapshot.json

## test: run all tests with race detector
test:
	go test -race ./...

## lint: run go vet and staticcheck
lint:
	go vet ./...

## build: compile the server binary locally (Tailwind CSS must already be compiled)
build:
	CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /tmp/lph-frontend ./cmd/server
