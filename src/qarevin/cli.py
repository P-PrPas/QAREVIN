"""Owner CLI. No command enables real-money trading."""
import argparse
import json
from pathlib import Path

from qarevin import __version__
from qarevin.domain import digest, load_config
from qarevin.resources import preflight


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="qarevin")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("config-check")
    check.add_argument("path", type=Path)
    resource = sub.add_parser("preflight")
    resource.add_argument("--job-memory-mib", type=int, default=768)
    args = parser.parse_args(argv)
    if args.command == "config-check":
        config = load_config(args.path)
        print(json.dumps({"valid": True, "environment": config.environment, "hash": digest(config)}))
    elif args.command == "preflight":
        result = preflight(args.job_memory_mib)
        print(json.dumps(result))
        if not result["ready"]:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
