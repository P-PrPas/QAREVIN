"""Structured, allowlisted operational logging: never logs arbitrary text or config."""
import logging
import math

from qarevin.domain import canonical_json, utc_now

ALLOWED_FIELDS = {"job_id", "dataset_id", "strategy_hash", "status", "error_type", "duration_seconds"}


def event(logger: logging.Logger, name: str, **fields) -> None:
    if name not in {"started", "succeeded", "failed", "deferred", "denied"}:
        raise ValueError("unknown audit event")
    payload = {key: value for key, value in fields.items() if key in ALLOWED_FIELDS}
    # Only bounded machine identifiers/numbers are loggable. Free-form provider errors stay out.
    payload = {key: value for key, value in payload.items()
               if (type(value) in (int, float) and math.isfinite(value)) or
               (isinstance(value, str) and len(value) <= 128 and all(c.isalnum() or c in '_-.' for c in value))}
    logger.info(canonical_json({"timestamp": utc_now(), "event": name, **payload}))
