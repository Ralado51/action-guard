import json
import sys
from pathlib import Path

import pytest
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONTRACTS = ROOT / "contracts"
EXAMPLES = CONTRACTS / "examples"
SCENARIOS = ["success", "owner_changed", "task_missing", "inconclusive",
             "evidence_missing", "case_deleted", "case_unconfirmed"]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def schemas():
    return {p.name.replace(".schema.json", ""): load(p) for p in CONTRACTS.glob("*.schema.json")}


@pytest.fixture(scope="session")
def registry(schemas):
    resources = [(s["$id"], Resource.from_contents(s)) for s in schemas.values()]
    return Registry().with_resources(resources)


@pytest.fixture(scope="session")
def validator(schemas, registry):
    from jsonschema import Draft202012Validator

    def make(name: str):
        return Draft202012Validator(schemas[name], registry=registry)

    return make
