import math

import pytest
from pydantic import ValidationError

from qarevin.domain import ResearchConfig, RiskPolicy, SessionPolicy, canonical_json, digest


def test_research_has_no_credentials_or_live_toggle(config):
    payload = config.model_dump()
    for extra in ({"environment": "live"}, {"broker_password": "forbidden"}, {"live_enabled": True}):
        with pytest.raises(ValidationError):
            ResearchConfig.model_validate(payload | extra)
    with pytest.raises(ValueError, match="unverified"):
        config.require_demo_ready()


def test_policy_is_bounded_finite_and_frozen():
    for value in (0, -1, math.nan, math.inf, 0.01):
        with pytest.raises(ValidationError):
            RiskPolicy(per_trade=value)
    with pytest.raises(ValidationError):
        RiskPolicy().daily_loss = 0.5
    with pytest.raises(ValidationError):
        SessionPolicy(timezone="UTC", entry_start_hour=20, entry_end_hour=10, flatten_hour=21)


def test_hash_is_canonical_and_nonfinite_rejected():
    assert digest({"a": 1, "b": 2}) == digest({"b": 2, "a": 1})
    with pytest.raises(ValueError):
        canonical_json({"profit": math.inf})
