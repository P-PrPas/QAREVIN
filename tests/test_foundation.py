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

@pytest.mark.parametrize("payload", [{"risk_day_timezone": "Mars/Olympus"}, {"max_positions": True}])
def test_review_invalid_policy_is_validation_error(payload):
    with pytest.raises(ValidationError):
        RiskPolicy.model_validate(payload)


def test_review_duplicate_keys_rejected(tmp_path):
    from qarevin.domain import load_config
    path = tmp_path / 'bad.json'
    path.write_text('{"environment":"research","environment":"live"}')
    with pytest.raises(ValueError, match="duplicate"):
        load_config(path)


def test_registry_migration_backup_and_log_redaction(tmp_path, caplog):
    import logging
    import sqlite3
    from qarevin.audit import event
    from qarevin.registry import Registry
    path = tmp_path / 'registry.sqlite'
    registry = Registry(path)
    assert registry.db.execute('SELECT version FROM schema_migrations').fetchone() == (1,)
    registry.backup(tmp_path / 'backup.sqlite')
    registry.close()
    with sqlite3.connect(tmp_path / 'backup.sqlite') as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    with caplog.at_level(logging.INFO):
        event(logging.getLogger('test'), 'failed', password='sensitive', error='Bearer sensitive', status='failed')
    assert 'sensitive' not in caplog.text and 'failed' in caplog.text


def test_strict_contract_and_version_identity(config):
    from qarevin.domain import InstrumentSpec, version_identity
    for patch in ({'volume_step': 5}, {'tick_size': 0.001}, {'account_currency': '', 'profit_currency': ''}):
        with pytest.raises(ValidationError):
            InstrumentSpec.model_validate(config.instrument.model_dump() | patch)
    assert version_identity(config) != digest(config)
    with pytest.raises(ValidationError):
        ResearchConfig.model_validate(config.model_dump() | {'initial_equity': '1000'})


def test_cli_errors_do_not_echo_payload(capsys, tmp_path):
    from qarevin.cli import main
    path = tmp_path / 'bad.json'
    path.write_text('{"secret":"sensitive"}')
    with pytest.raises(SystemExit) as exc:
        main(['config-check', str(path)])
    assert exc.value.code == 2
    assert 'sensitive' not in capsys.readouterr().out


def test_final_review_edge_cases(config, tmp_path, caplog):
    import logging
    from qarevin.audit import event
    from qarevin.domain import InstrumentSpec, source_identity
    with pytest.raises(ValidationError):
        InstrumentSpec.model_validate(config.instrument.model_dump() | {'tick_size': 0.015})
    with caplog.at_level(logging.INFO):
        event(logging.getLogger('test'), 'failed', duration_seconds=float('nan'))
    assert 'NaN' not in caplog.text and 'failed' in caplog.text
    assert len(source_identity()) == 64
