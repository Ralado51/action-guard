"""Runtime probes. Run separately; do not infer these results from Docker flags."""
import json
import os
import socket
from pathlib import Path

result={'non_root':os.getuid()!=0,'network_disabled':False,'root_write_blocked':False,
        'no_integration_credentials':not any(k.startswith(('SF_','VULTR_','ACTION_GUARD_API_TOKEN')) for k in os.environ),
        'no_docker_socket':not Path('/var/run/docker.sock').exists()}
try:
    sock=socket.socket()
    sock.settimeout(2)
    sock.connect(('1.1.1.1',443))
except OSError:
    result['network_disabled']=True
finally:
    sock.close()
try:
    Path('/app/forbidden-probe').write_text('probe')
except OSError:
    result['root_write_blocked']=True
print(json.dumps(result))
raise SystemExit(0 if all(result.values()) else 1)
