"""Fixed endpoint methods rather than an agent-controlled arbitrary HTTP client."""
import os
from pathlib import Path

import httpx


class Client:
    def __init__(self, url: str, token: str, *, transport=None):
        if not (url.startswith('http://') or url.startswith('https://')) or len(token) < 32:
            raise ValueError('configured API URL and agent token required')
        self.http = httpx.Client(base_url=url.rstrip('/'),headers={'Authorization':'Bearer '+token},
                                 timeout=20,transport=transport,follow_redirects=False,trust_env=False)

    def request(self, method: str, path: str, body=None):
        allowed = (('GET','datasets'),('GET','status'),('POST','hypotheses'),('POST','candidates'),
                   ('POST','jobs'),('POST','compare'),('POST','registry/candidates'),('POST','promotions/live'),('GET','memory'),('POST','memory'),('POST','promotions/demo'))
        parts=path.split('/')
        dynamic = ((len(parts)==2 and parts[0]=='jobs' and method=='GET') or
                   (len(parts)==3 and parts[0]=='jobs' and parts[2] in ('result','cancel') and
                    method==('GET' if parts[2]=='result' else 'POST')) or
                   (len(parts)==3 and parts[0]=='candidates' and parts[2]=='lineage' and method=='GET'))
        if (method,path) not in allowed and not dynamic:
            raise ValueError('endpoint not allowed')
        if any(not part or not all(c.isalnum() or c in '_-' for c in part) for part in parts):
            raise ValueError('invalid path segment')
        response=self.http.request(method,'/api/v1/'+path,json=body if body is not None else None)
        if not response.is_success:
            raise RuntimeError(f'control_api_{response.status_code}')
        return response.json()

    def close(self):
        self.http.close()


def from_environment():
    path=Path(os.environ['QAREVIN_AGENT_TOKEN_FILE'])
    if path.stat().st_mode & 0o077:
        raise ValueError('token file permissions must be owner-only')
    return Client(os.environ['QAREVIN_API_URL'],path.read_text().strip())
