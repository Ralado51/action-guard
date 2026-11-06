"""Fixed evaluator entrypoint: JSON in, JSON out; never executes generated code."""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/app')
from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from contracts.semantics import validate_snapshot_pair
from engine import evaluate

MAX_BYTES = 2 * 1024 * 1024


def process(payload, root=None):
    root = Path(root or Path(__file__).resolve().parents[1] / 'contracts')
    schemas = {p.name: json.loads(p.read_text()) for p in root.glob('*.schema.json')}
    registry = Registry().with_resources([(s['$id'], Resource.from_contents(s)) for s in schemas.values()])
    if not isinstance(payload, dict) or set(payload) != {'plan', 'before', 'after'}:
        raise ValueError('Expected plan, before and after only')
    for key, schema in [('plan','test_plan.schema.json'),('before','snapshot.schema.json'),('after','snapshot.schema.json')]:
        Draft202012Validator(schemas[schema], registry=registry).validate(payload[key])
    if validate_snapshot_pair(payload['plan'],payload['before'],payload['after']):
        # Missing fields are handled by the engine; identity conflicts cannot be trusted.
        b,a=payload['before'],payload['after']
        if b['run_id']!=a['run_id'] or b['primary_record']!=a['primary_record']:
            raise ValueError('Incompatible evidence')
    results, changes = evaluate(payload['plan'],payload['before'],payload['after'])
    validator = Draft202012Validator(schemas['check_result.schema.json'], registry=registry)
    for result in results:
        validator.validate(result)
    return {'results': results, 'unexpected_changes': changes}


def main():
    try:
        raw=sys.stdin.buffer.read(MAX_BYTES+1)
        if len(raw)>MAX_BYTES: raise ValueError('Input too large')
        print(json.dumps(process(json.loads(raw)),ensure_ascii=False))
        return 0
    except Exception:
        print(json.dumps({'error':'invalid_or_unverifiable_evidence'}))
        return 2


if __name__=='__main__':
    raise SystemExit(main())
