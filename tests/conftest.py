from pathlib import Path

import pytest

from qarevin.domain import load_config


@pytest.fixture
def config():
    return load_config(Path(__file__).parents[1] / "config/research.example.json")
