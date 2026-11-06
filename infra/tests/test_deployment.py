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


def test_every_package_the_web_app_imports_is_in_the_image():
    """The app imports more than it used to (acceptance, calibration, vultr_agent): the image must carry all of it."""
    import subprocess, sys, json
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    code = ("import sys, json; sys.path.insert(0, %r); import web.app.main; "
            "print(json.dumps(sorted({m.split('.')[0] for m, mod in sys.modules.items() "
            "if getattr(mod, '__file__', None) and str(mod.__file__).startswith(%r + '/') }))) " % (str(root), str(root)))
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=root, check=True).stdout
    packages = [p for p in json.loads(out.strip().splitlines()[-1]) if (root / p).is_dir() and p not in ("tests", "infra")]
    dockerfile = (root / "infra" / "Dockerfile").read_text()
    ignore = (root / "infra" / "Dockerfile.dockerignore").read_text()
    for p in packages:
        assert f"COPY {p} ./{p}" in dockerfile, f"{p} is imported by the web app but not copied into the image"
        assert f"!{p}/**" in ignore, f"{p} is excluded by the docker build context"
