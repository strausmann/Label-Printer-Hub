# label-printer-hub — backend

Python/FastAPI backend for the [Label Printer Hub](https://github.com/strausmann/label-printer-hub).

This subdirectory builds an installable Python package and a container image. Project-level documentation, architecture decisions, and the user wiki live in the [repository root](https://github.com/strausmann/label-printer-hub).

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
uvicorn app.main:app --reload
```

The backend exposes its OpenAPI spec at `/openapi.json`, Swagger UI at `/docs`, and ReDoc at `/redoc` (see [ADR 0011](../docs/decisions/0011-openapi-as-api-contract.md)).

## Container

The `Dockerfile` here produces the `ghcr.io/strausmann/label-printer-hub-backend` image — see the [tag scheme ADR](../docs/decisions/0007-docker-image-tag-scheme.md) for which tags every release publishes.

## License

MIT — see [LICENSE](../LICENSE) in the repository root.
