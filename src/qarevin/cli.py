"""Owner CLI. No command enables real-money trading."""
import argparse
import json
from pathlib import Path

from qarevin import __version__
from qarevin.domain import load_config, version_identity
from qarevin.resources import preflight


def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qarevin")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("config-check")
    check.add_argument("path", type=Path)
    resource = sub.add_parser("preflight")
    resource.add_argument("--job-memory-mib", type=int, default=768)
    resource.add_argument("--config", type=Path)
    args = parser.parse_args(argv)
    if args.command == "config-check":
        config = load_config(args.path)
        print(json.dumps({"valid": True, "environment": config.environment, "hash": version_identity(config)}))
    elif args.command == "preflight":
        result = preflight(args.job_memory_mib, load_config(args.config).memory_reserve_mib if args.config else 1024)
        print(json.dumps(result))
        if not result["ready"]:
            raise SystemExit(2)


def main(argv: list[str] | None = None) -> None:
    try:
        _main(argv)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"valid": False, "error_type": type(exc).__name__}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
