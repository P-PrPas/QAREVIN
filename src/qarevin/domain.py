"""Strict, frozen contracts shared by research and guarded execution."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


RESEARCH_BOUNDARY = '2025-01-01T00:00:00Z'


class Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False, strict=True)


def canonical_json(value: Any) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def file_digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Environment(StrEnum):
    RESEARCH = "research"
    DEMO = "demo"
    LIVE = "live"


class InstrumentSpec(Contract):
    symbol: str = Field(min_length=1, max_length=64)
    account_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    profit_currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    point: float = Field(gt=0)
    tick_size: float = Field(gt=0)
    tick_value: float = Field(gt=0)
    contract_size: float = Field(gt=0)
    volume_min: float = Field(gt=0)
    volume_step: float = Field(gt=0)
    volume_max: float = Field(gt=0)
    margin_per_lot: float = Field(gt=0)
    stop_distance_min: float = Field(default=0, ge=0)
    # stop_distance_min is an absolute price distance, NOT MT5 points.
    verified: bool = False

    @model_validator(mode="after")
    def consistent(self) -> InstrumentSpec:
        for value in (self.volume_min, self.volume_max):
            if not math.isclose(value / self.volume_step, round(value / self.volume_step), abs_tol=1e-8):
                raise ValueError("volume bounds must align with step")
        if not math.isclose(self.tick_size / self.point, round(self.tick_size / self.point), abs_tol=1e-8):
            raise ValueError("tick_size must align with point")
        if self.tick_size < self.point:
            raise ValueError("tick_size below point")
        if self.volume_max < self.volume_min:
            raise ValueError("volume_max below volume_min")
        if self.profit_currency != self.account_currency:
            raise ValueError("currency conversion unsupported until an explicit FX model is supplied")
        return self


class CostModel(Contract):
    spread_points: float = Field(ge=0)
    slippage_points: float = Field(ge=0)
    commission_per_lot_side: float = Field(ge=0)
    spread_multiplier: float = Field(default=1, ge=1, le=10)
    verified: bool = False


class RiskPolicy(Contract):
    per_trade: float = Field(default=0.0025, gt=0, le=0.0025)
    daily_loss: float = Field(default=0.01, gt=0, le=0.01)
    max_drawdown: float = Field(default=0.05, gt=0, le=0.05)
    max_margin_fraction: float = Field(default=0.25, gt=0, le=0.5)
    max_positions: int = Field(default=1, ge=1, le=1)
    max_spread_points: float = Field(default=100, gt=0)
    max_quote_age_seconds: float = Field(default=10, gt=0)
    risk_day_timezone: str = "UTC"

    @field_validator("risk_day_timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        checked_timezone(value)
        return value


class SessionPolicy(Contract):
    timezone: str
    entry_start_hour: int = Field(ge=0, le=23)
    entry_end_hour: int = Field(ge=0, le=23)
    flatten_hour: int = Field(ge=0, le=23)
    verified: bool = False

    @model_validator(mode="after")
    def valid_window(self) -> SessionPolicy:
        checked_timezone(self.timezone)
        if not self.entry_start_hour < self.entry_end_hour <= self.flatten_hour:
            raise ValueError("require start < end <= flatten; overnight sessions unsupported")
        return self


class ResearchConfig(Contract):
    research_access_before: str = Field(default=RESEARCH_BOUNDARY,validate_default=True)
    released_data_record_hash: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    environment: Literal["research"] = "research"
    initial_equity: float = Field(default=1000, gt=0)
    daily_experiments: int = Field(default=5, ge=1, le=20)
    worker_concurrency: int = Field(default=1, ge=1, le=1)
    job_timeout_seconds: int = Field(default=900, ge=1, le=3600)
    memory_reserve_mib: int = Field(default=1024, ge=256)
    instrument: InstrumentSpec
    costs: CostModel
    risk: RiskPolicy = RiskPolicy()
    session: SessionPolicy

    @field_validator('research_access_before')
    @classmethod
    def access_boundary(cls,value):
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('research boundary must be timezone-aware')
        return stamp.astimezone(timezone.utc).isoformat()

    @model_validator(mode='after')
    def released_data_policy(self):
        if datetime.fromisoformat(self.research_access_before)>datetime.fromisoformat(RESEARCH_BOUNDARY.replace('Z','+00:00')) and not self.released_data_record_hash:
            raise ValueError('extending research access requires owner release-record hash')
        return self

    def require_demo_ready(self) -> None:
        if not all((self.instrument.verified, self.costs.verified, self.session.verified)):
            raise ValueError("unverified instrument, costs or sessions; demo blocked")


def checked_timezone(value: str) -> str:
    if value == "localtime":
        raise ValueError("host-dependent timezone prohibited")
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("unknown timezone") from exc
    return value


def unique_json(text: str) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=pairs)


def load_config(path: Path) -> ResearchConfig:
    return ResearchConfig.model_validate(unique_json(path.read_text()))


def version_identity(config: ResearchConfig) -> str:
    from qarevin import __version__
    return digest({"schema_version": 1, "package_version": __version__, "source_hash": source_identity(), "config": config.model_dump(mode="json")})


def finite(value: float, name: str) -> float:
    if not math.isfinite(value):
        raise ValueError(f"{name} must be finite")
    return value


def source_identity() -> str:
    root = Path(__file__).parent
    return digest({str(path.relative_to(root)): file_digest(path) for path in sorted(root.rglob("*.py"))})
