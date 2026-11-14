# Labelyard — backend

Python/FastAPI backend for the [Labelyard](https://github.com/strausmann/labelyard), the self-hosted Label Printer Hub.

This subdirectory builds an installable Python package and a container image. Project-level documentation, architecture decisions, and the user wiki live in the [repository root](https://github.com/strausmann/labelyard).

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -v
uvicorn app.main:app --reload
```

The backend exposes its OpenAPI spec at `/openapi.json`, and the interactive Scalar API reference at `/docs` (see [ADR 0011](../docs/decisions/0011-openapi-as-api-contract.md)).

## Container

The `Dockerfile` here produces the `ghcr.io/strausmann/labelyard` image — see the [tag scheme ADR](../docs/decisions/0007-docker-image-tag-scheme.md) for which tags every release publishes.

## License

AGPL-3.0-or-later — see [LICENSE](../LICENSE) in the repository root.
