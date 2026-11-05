"""Immutable MT5 CSV ingestion. Unknown timezone and invalid bars fail explicitly."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from qarevin.domain import canonical_json, digest, file_digest, utc_now

PRICE_COLUMNS = ["open", "high", "low", "close"]


def validate_bars(frame: pd.DataFrame) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex) or frame.index.tz is None:
        raise ValueError("bars require timezone-aware index")
    if frame.empty or not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("empty, unordered or duplicate bars")
    if not (frame.index == frame.index.floor("min")).all():
        raise ValueError("M1 timestamps must align to minute opens")
    values = frame[PRICE_COLUMNS].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValueError("nonfinite or nonpositive OHLC")
    if ((frame.high < frame[PRICE_COLUMNS].max(axis=1)) |
            (frame.low > frame[PRICE_COLUMNS].min(axis=1))).any():
        raise ValueError("invalid OHLC bounds")
    for column in ("tick_volume", "real_volume", "spread_points"):
        if column in frame:
            values = frame[column].to_numpy(dtype=float)
            if not np.isfinite(values).all() or (values < 0).any():
                raise ValueError(f"invalid {column}")


def _normalize(chunk: pd.DataFrame, source_timezone: str) -> pd.DataFrame:
    chunk.columns = [c.strip("<>").lower() for c in chunk.columns]
    if {"date", "time"} <= set(chunk.columns):
        timestamp = pd.to_datetime(chunk.pop("date").astype(str) + " " + chunk.pop("time").astype(str), format="%Y.%m.%d %H:%M:%S")
    elif "timestamp" in chunk:
        timestamp = pd.to_datetime(chunk.pop("timestamp"), format="ISO8601")
    else:
        raise ValueError("CSV requires timestamp or MT5 <DATE>/<TIME>")
    index = pd.DatetimeIndex(timestamp)
    if index.tz is None:
        index = index.tz_localize(source_timezone, ambiguous="raise", nonexistent="raise")
    elif source_timezone != "UTC":
        raise ValueError("offset-aware input must declare UTC normalization")
    chunk.index = index.tz_convert("UTC")
    chunk.index.name = "timestamp_utc"
    chunk = chunk.rename(columns={"tickvol": "tick_volume", "vol": "real_volume", "spread": "spread_points"})
    for col in PRICE_COLUMNS:
        chunk[col] = pd.to_numeric(chunk[col], errors="raise")
    for col in ("tick_volume", "real_volume"):
        if col not in chunk:
            chunk[col] = 0
    for col in ("tick_volume", "real_volume", "spread_points"):
        if col in chunk:
            chunk[col] = pd.to_numeric(chunk[col], errors="raise")
    validate_bars(chunk)
    return chunk


def import_csv(source: Path, store: Path, *, source_timezone: str, provider: str,
               symbol: str, accessible_before: str | None = None, chunksize: int = 100_000) -> dict:
    ZoneInfo(source_timezone)
    if not provider.strip() or not symbol.strip() or chunksize < 1:
        raise ValueError("provider, symbol and positive chunksize required")
    if source.is_symlink() or not source.is_file():
        raise ValueError("source must be a regular non-symlink file")
    raw_hash = file_digest(source)
    identity = {"raw_sha256": raw_hash, "source_timezone": source_timezone,
                "provider": provider, "symbol": symbol, "schema": 1,
                "accessible_before": accessible_before}
    dataset_id = digest(identity)
    store.mkdir(parents=True, exist_ok=True)
    destination = store / dataset_id
    if destination.exists():
        return read_manifest(destination)
    temp = Path(tempfile.mkdtemp(prefix=".import-", dir=store))
    try:
        shutil.copyfile(source, temp / "raw.csv")
        if file_digest(temp / "raw.csv") != raw_hash:
            raise ValueError("source changed during import")
        with (temp / "raw.csv").open() as stream:
            first = stream.readline()
        delimiter = "\t" if "\t" in first else "," if "," in first else ";"
        previous = None
        first_time = None
        count = gaps = 0
        partitions = []
        for number, chunk in enumerate(pd.read_csv(temp / "raw.csv", sep=delimiter, chunksize=chunksize)):
            bars = _normalize(chunk, source_timezone)
            if accessible_before and bars.index.max() >= pd.Timestamp(accessible_before, tz="UTC"):
                raise ValueError("data crosses accessible research boundary; use a separate owner-only holdout import")
            if previous is not None and bars.index[0] <= previous:
                raise ValueError("unordered or duplicate bars across chunks")
            differences = bars.index.to_series().diff().dropna()
            gaps += int((differences > pd.Timedelta(minutes=1)).sum())
            if previous is not None and bars.index[0] - previous > pd.Timedelta(minutes=1):
                gaps += 1
            first_time = first_time or bars.index[0].isoformat()
            previous = bars.index[-1]
            for year, subset in bars.groupby(bars.index.year):
                name = f"{year}-{number:06d}.parquet"
                subset.to_parquet(temp / name)
                partitions.append({"path": name, "sha256": file_digest(temp / name), "rows": len(subset)})
            count += len(bars)
        if not count:
            raise ValueError("no bars")
        manifest = identity | {"id": dataset_id, "created_at": utc_now(), "rows": count,
                               "start": first_time, "end": previous.isoformat(),
                               "partitions": partitions,
                               "qa": {"valid": True, "gap_count": gaps, "gap_classification": "unknown_without_broker_calendar",
                                      "price_basis": "unverified_bid_assumption", "tick_path_available": False}}
        (temp / "manifest.json").write_text(canonical_json(manifest))
        temp.rename(destination)
        return manifest
    finally:
        if temp.exists():
            shutil.rmtree(temp)


def read_manifest(directory: Path) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text())
    if manifest["id"] != directory.name:
        raise ValueError("dataset identity mismatch")
    if file_digest(directory / "raw.csv") != manifest["raw_sha256"]:
        raise ValueError("raw file hash mismatch")
    return manifest


def load_dataset(directory: Path, start: str | None = None, end: str | None = None) -> pd.DataFrame:
    manifest = read_manifest(directory)
    frames = []
    for partition in manifest["partitions"]:
        path = directory / partition["path"]
        if path.parent.resolve() != directory.resolve() or path.is_symlink():
            raise ValueError("invalid partition path")
        if file_digest(path) != partition["sha256"]:
            raise ValueError("partition hash mismatch")
        frame = pd.read_parquet(path)
        if start:
            frame = frame[frame.index >= pd.Timestamp(start)]
        if end:
            frame = frame[frame.index < pd.Timestamp(end)]
        frames.append(frame)
    result = pd.concat(frames)
    validate_bars(result)
    return result


def resample(bars: pd.DataFrame, minutes: int) -> pd.DataFrame:
    validate_bars(bars)
    if minutes not in (15, 30, 60):
        raise ValueError("supported timeframes: 15/30/60")
    group = bars.resample(f"{minutes}min", origin="epoch", closed="left", label="left")
    result = group.agg({"open": "first", "high": "max", "low": "min", "close": "last", "tick_volume": "sum", "real_volume": "sum"})
    result["complete"] = group["close"].count().eq(minutes)
    # Empty/incomplete buckets cannot create tradable indicators.
    result = result[result["complete"]].copy()
    result.index += pd.Timedelta(minutes=minutes)
    result.index.name = "available_at_utc"
    return result
