#!/usr/bin/env python3
"""Create dedicated local research directories/token, without starting services."""
import secrets
from pathlib import Path

root=Path(__file__).resolve().parents[1]
for name in ('state','data','secrets'):
    path=root/name
    if path.is_symlink():
        raise SystemExit('refusing symlinked runtime directory')
    path.mkdir(exist_ok=True,mode=0o700)
target=root/'secrets/agent_token'
if not target.exists():
    fd=__import__('os').open(target,__import__('os').O_CREAT|__import__('os').O_EXCL|__import__('os').O_WRONLY,0o600)
    with __import__('os').fdopen(fd,'w') as stream:
        stream.write(secrets.token_urlsafe(48))
else:
    if target.is_symlink() or target.stat().st_mode & 0o077:
        raise SystemExit('existing token must be non-symlink and owner-only')
print('Dedicated research directories/token ready. Token contents are never printed. No service started.')
