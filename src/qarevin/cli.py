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
    ingest = sub.add_parser("import")
    ingest.add_argument("source", type=Path)
    ingest.add_argument("--store", required=True, type=Path)
    ingest.add_argument("--timezone", required=True)
    ingest.add_argument("--provider", required=True)
    ingest.add_argument("--symbol", required=True)
    ingest.add_argument("--accessible-before", default="2025-01-01")
    qa = sub.add_parser("data-qa")
    qa.add_argument("dataset", type=Path)
    backtest = sub.add_parser("backtest")
    backtest.add_argument("dataset", type=Path)
    backtest.add_argument("--config", required=True, type=Path)
    backtest.add_argument("--family", choices=["trend", "mean_reversion", "breakout", "no_trade", "random"], required=True)
    backtest.add_argument("--output", type=Path, required=True)
    replay = sub.add_parser("replay")
    replay.add_argument("artifact", type=Path)
    replay.add_argument("dataset", type=Path)
    replay.add_argument("--config", required=True, type=Path)
    report = sub.add_parser("report")
    report.add_argument("artifact", type=Path)
    evaluation = sub.add_parser("evaluate")
    evaluation.add_argument("artifact", type=Path)
    evaluation.add_argument("--config", required=True, type=Path)
    comparison = sub.add_parser("compare")
    comparison.add_argument("baseline", type=Path)
    comparison.add_argument("challenger", type=Path)
    comparison.add_argument("--config", required=True, type=Path)
    experiment = sub.add_parser("experiment")
    experiment.add_argument("dataset", type=Path)
    experiment.add_argument("--config", type=Path, required=True)
    experiment.add_argument("--family", required=True, choices=["trend", "mean_reversion", "breakout", "no_trade", "random"])
    experiment.add_argument("--hypothesis", required=True)
    experiment.add_argument("--state", type=Path, required=True)
    reproduce = sub.add_parser("replay-experiment")
    reproduce.add_argument("artifact", type=Path)
    reproduce.add_argument("dataset", type=Path)
    walk = sub.add_parser("walk-forward")
    walk.add_argument("dataset", type=Path)
    walk.add_argument("--config", required=True, type=Path)
    walk.add_argument("--protocol", required=True, type=Path, help="JSON with candidates and exact folds")
    walk.add_argument("--state", type=Path, default=Path.home() / ".local/share/qarevin")
    walk.add_argument("--output", type=Path, required=True)
    backup = sub.add_parser("backup")
    backup.add_argument("registry", type=Path)
    backup.add_argument("destination", type=Path)
    args = parser.parse_args(argv)
    if args.command in ("evaluate", "compare"):
        from qarevin.artifacts import read_artifact
        from qarevin.evaluation import compare, evaluate
        config = load_config(args.config)
        if args.command == "evaluate":
            answer = evaluate(read_artifact(args.artifact)["result"], config)
        else:
            answer = compare(evaluate(read_artifact(args.baseline)["result"], config),
                             evaluate(read_artifact(args.challenger)["result"], config))
        print(json.dumps(answer, indent=2))
    elif args.command == "experiment":
        from qarevin.evidence import EvidenceStore
        from qarevin.experiments import run_experiment
        from qarevin.strategies import StrategySpec
        answer = run_experiment(args.dataset, load_config(args.config), StrategySpec(family=args.family),
                                args.hypothesis, EvidenceStore(args.state / "registry.sqlite"), args.state / "artifacts")
        print(json.dumps(answer))
    elif args.command == "replay-experiment":
        from qarevin.experiments import replay_experiment
        print(json.dumps(replay_experiment(args.artifact, args.dataset)))
    elif args.command == "walk-forward":
        from qarevin.artifacts import write_artifact
        from qarevin.data import load_dataset
        from qarevin.domain import unique_json
        from qarevin.strategies import StrategySpec
        from qarevin.walkforward import Fold, walk_forward
        from qarevin.evidence import EvidenceStore
        protocol = unique_json(args.protocol.read_text())
        result = walk_forward(load_dataset(args.dataset), load_config(args.config),
                              [StrategySpec.model_validate(item) for item in protocol["candidates"]],
                              [Fold.model_validate(item) for item in protocol["folds"]],
                              store=EvidenceStore(args.state / "registry.sqlite"))
        print(json.dumps({"artifact": str(write_artifact(args.output, result))}))
    elif args.command == "backup":
        from qarevin.evidence import EvidenceStore
        EvidenceStore(args.registry).backup(args.destination)
        print(json.dumps({"backup": str(args.destination)}))
    elif args.command == "import":
        from qarevin.data import import_csv
        print(json.dumps(import_csv(args.source, args.store, source_timezone=args.timezone,
                                    provider=args.provider, symbol=args.symbol,
                                    accessible_before=args.accessible_before)))
    elif args.command == "data-qa":
        from qarevin.data import load_dataset, read_manifest
        load_dataset(args.dataset)
        print(json.dumps(read_manifest(args.dataset)))
    elif args.command in ("backtest", "replay"):
        from qarevin.artifacts import read_artifact, write_artifact
        from qarevin.backtest import run_backtest
        from qarevin.data import load_dataset, read_manifest
        from qarevin.domain import source_identity
        from qarevin.strategies import StrategySpec
        config = load_config(args.config)
        manifest = read_manifest(args.dataset)
        original = read_artifact(args.artifact) if args.command == "replay" else None
        strategy = StrategySpec.model_validate(original["result"]["strategy"]) if original else StrategySpec(family=args.family)
        result = run_backtest(load_dataset(args.dataset), config, strategy)
        payload = {"dataset_id": manifest["id"], "source_hash": source_identity(), "result": result}
        if original:
            if payload != original:
                raise ValueError("replay mismatch: code, data, configuration or results changed")
            print(json.dumps({"reproduced": True, "result_hash": result["result_hash"]}))
        else:
            print(json.dumps({"artifact": str(write_artifact(args.output, payload)), "result_hash": result["result_hash"]}))
    elif args.command == "report":
        from qarevin.artifacts import read_artifact
        payload = read_artifact(args.artifact)
        result = payload["result"]
        print(json.dumps({"dataset_id": payload["dataset_id"], "initial_equity": result["initial_equity"],
                          "final_equity": result["final_equity"], "trades": len(result["trades"]),
                          "limitations": result["limitations"], "promotion_ready": False}, indent=2))
    elif args.command == "config-check":
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
    except (ValueError, OSError, KeyError, RecursionError) as exc:
        print(json.dumps({"valid": False, "error_type": type(exc).__name__}))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
