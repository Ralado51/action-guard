"""Static deployment policy and startup validation; no Docker daemon required."""
import runpy
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
validate = runpy.run_path(str(ROOT / 'start.py'))['validate']


@pytest.mark.parametrize('env', [{}, {'ACTION_GUARD_API_TOKEN': 'x' * 32}, {'ACTION_GUARD_API_TOKEN': 'short', 'ACTION_GUARD_DEMO_MODE': 'true'}, {'ACTION_GUARD_API_TOKEN': 'x' * 32, 'ACTION_GUARD_DEMO_MODE': 'typo'}])
def test_startup_rejects_incomplete_or_unsafe_config(env):
    with pytest.raises(ValueError):
        validate(env)


@pytest.mark.parametrize('mode', ['true', 'false'])
def test_startup_accepts_explicit_mode(mode):
    validate({'ACTION_GUARD_API_TOKEN': 'x' * 48, 'ACTION_GUARD_DEMO_MODE': mode})


def test_deployment_has_no_data_or_credentials_in_image():
    text = (ROOT / 'Dockerfile').read_text()
    assert 'COPY . .' not in text
    assert 'COPY runs' not in text
    assert 'COPY .env' not in text
    assert 'USER 10001:10001' in text
