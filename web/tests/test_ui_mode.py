"""Button policy regression without a browser or external services."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_mode_does_not_restore_execute_after_submission():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node unavailable')
    source = (Path(__file__).resolve().parents[1] / 'static' / 'app.js').read_text()
    function = next(line for line in source.splitlines() if line.startswith('function applyMode('))
    script = '''
const assert = require('node:assert/strict');
const button = {hidden:true, disabled:false};
const $ = () => button;
let plan={approval:{}}, executionEnabled=true, busy=false;
''' + function + '''
applyMode(); assert.equal(button.hidden,true);
applyMode(true); assert.equal(button.hidden,false);
busy=true; applyMode(); assert.equal(button.disabled,true);
executionEnabled=false; applyMode(true);
assert.equal(button.hidden,true); assert.equal(button.disabled,true);
'''
    subprocess.run([node, '-e', script], check=True, timeout=5)
