"""Host-side Docker runner. No socket or credentials are mounted in the evaluator."""
import json
import subprocess
import uuid
from datetime import datetime, timezone

MAX_BYTES=2*1024*1024


class SandboxError(Exception):
    def __init__(self,message,events):
        super().__init__(message)
        self.events=events


def stamp():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def command(image,name,probe=False):
    args=['docker','run','--rm','-i','--name',name,'--network','none','--read-only',
          '--user','65532:65532','--cap-drop','ALL','--security-opt','no-new-privileges:true',
          '--pids-limit','32','--memory','128m','--memory-swap','128m','--cpus','0.5',
          '--ulimit','nofile=64:64','--tmpfs','/tmp:rw,noexec,nosuid,size=8m','--log-driver','none']
    for key in ('HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','http_proxy','https_proxy','all_proxy','no_proxy'):
        args+=['--env',key+'=']
    if probe:args+=['--entrypoint','python']
    args+=[image]
    if probe:args+=['-I','/app/probe.py']
    return args


def run(payload=None,*,image='action-guard-evaluator',timeout=15,probe=False,invoke=subprocess.run):
    raw=json.dumps(payload).encode() if payload is not None else b''
    if len(raw)>MAX_BYTES:raise SandboxError('Evidence exceeds input limit',[])
    name='ag-eval-'+uuid.uuid4().hex
    events=[]
    result=None
    failure=None
    try:
        result=invoke(command(image,name,probe),input=raw,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                      timeout=timeout,check=False)
    except subprocess.TimeoutExpired:
        events.append({'type':'timeout','blocked':True,'at':stamp(),'detail':'Evaluator exceeded host wall-clock deadline; cleanup requested.'})
        failure='Evaluator timed out'
    except OSError:
        failure='Docker unavailable; no host fallback was used'
    finally:
        try:
            cleaned=invoke(['docker','rm','-f',name],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=5,check=False)
            # --rm may already have removed it; distinguish absence from daemon failure.
            absent=cleaned.returncode==0 or b'No such container' in cleaned.stderr
            events.append({'type':'cleanup','blocked':absent,'at':stamp(),
                           'detail':'Container removed or already absent.' if absent else 'Cleanup could not be confirmed.'})
            if not absent:failure='Evaluator cleanup could not be confirmed'
        except (OSError,subprocess.TimeoutExpired):
            events.append({'type':'cleanup','blocked':False,'at':stamp(),'detail':'Cleanup could not be confirmed.'})
            failure='Evaluator cleanup could not be confirmed'
    if failure:raise SandboxError(failure,events)
    if result.returncode!=0:
        raise SandboxError('Evaluator did not return a successful result',events)
    try:
        if len(result.stdout)>MAX_BYTES*4:raise ValueError()
        output=json.loads(result.stdout)
        if not isinstance(output,dict):raise ValueError()
        if probe:
            if not output or not all(v is True for v in output.values()):raise ValueError()
        elif set(output)!={'results','unexpected_changes'} or not isinstance(output['results'],list):
            raise ValueError()
    except (ValueError,TypeError):
        raise SandboxError('Invalid evaluator output',events) from None
    return output,events
