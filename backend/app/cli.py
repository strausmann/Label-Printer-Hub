"""Container command line: ``printer-hub admin create-key`` (spec 8.2, D7).

Recovery when every admin key is lost. Whoever can run commands in the container
already controls the hub, so this adds no new attack surface — unlike a long-lived
key in an environment variable. The plaintext key is printed once on stdout.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.auth.dependencies import _SCOPE_ORDER


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="printer-hub", description="Label Printer Hub admin")
    groups = parser.add_subparsers(dest="group", required=True)
    admin = groups.add_parser("admin", help="administrative commands")
    commands = admin.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-key", help="create an API key and print it once")
    create.add_argument("--scope", required=True, choices=_SCOPE_ORDER)
    create.add_argument("--name", required=True)
    return parser


async def _create_key(scope: str, name: str) -> str:
    import app.db.engine as engine_module
    import app.models  # noqa: F401 — registers all tables
    from app.auth.key_generator import generate_api_key
    from app.models.api_key import ApiKey
    from app.repositories import api_keys as api_keys_repo

    plaintext, prefix, hashed = generate_api_key()
    async with engine_module.async_session() as db:
        await api_keys_repo.create(
            db,
            ApiKey(
                name=name,
                key_hash=hashed,
                key_prefix=prefix,
                scopes=[scope],
                allowed_printer_ids=[],
                enabled=True,
                notes="created with: printer-hub admin create-key",
            ),
        )
    return plaintext


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:  # argparse reports usage errors (2) and --help (0)
        return exc.code if isinstance(exc.code, int) else 2
    name = args.name.strip()
    if not name:
        sys.stderr.write("error: --name must not be empty\n")
        return 2
    try:
        plaintext = asyncio.run(_create_key(args.scope, name))
    except Exception as exc:
        sys.stderr.write(f"error: could not create the key: {exc}\n")
        return 1
    # The only place the plaintext ever appears: stdout, once.
    sys.stdout.write(plaintext + "\n")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
