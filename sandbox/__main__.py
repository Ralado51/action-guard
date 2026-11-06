import argparse
import json
from pathlib import Path
from .runner import SandboxError,run


def main():
    p=argparse.ArgumentParser(description='Offline Docker evaluation, never calls Salesforce')
    p.add_argument('--plan');p.add_argument('--before');p.add_argument('--after')
    p.add_argument('--probe',action='store_true');p.add_argument('--image',default='action-guard-evaluator')
    a=p.parse_args()
    if not a.probe and not all((a.plan,a.before,a.after)):p.error('provide --plan --before --after or --probe')
    try:
        payload=None if a.probe else {k:json.loads(Path(getattr(a,k)).read_text()) for k in ('plan','before','after')}
        result,events=run(payload,image=a.image,probe=a.probe)
        print(json.dumps({'ok':True,'result':result,'containment_events':events},indent=2))
        return 0
    except SandboxError as e:
        print(json.dumps({'ok':False,'error':str(e),'containment_events':e.events},indent=2))
        return 1


if __name__=='__main__':raise SystemExit(main())
