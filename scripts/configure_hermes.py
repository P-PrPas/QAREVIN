#!/usr/bin/env python3
"""Generate an isolated non-secret Qarevin Hermes profile; no service restart or key copying."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT=Path(__file__).resolve().parents[1]
DISABLED=['terminal','file','delegation','a2a','bot_room','browser','code_execution','computer_use',
          'connections','context_engine','cronjob','desktop_ui','discord','discord_admin','feishu_doc',
          'feishu_drive','homeassistant','image_gen','kanban','memory','project','search','session_search',
          'setup','spotify','stt','todo','tts','video','video_gen','web','x_search','yuanbao']


def configuration(base: dict, api_url: str) -> dict:
    model={key:value for key,value in base.get('model',{}).items() if key in ('default','provider','base_url')}
    if not model.get('default'):
        raise ValueError('base must declare model.default; model credentials stay owner-managed')
    for value in model.values():
        if not isinstance(value,str) or len(value)>512:
            raise ValueError('invalid non-secret model setting')
    url=urlsplit(model.get('base_url',''))
    if url.username or url.password or url.query or url.fragment:
        raise ValueError('model URL must contain no credentials or query')
    return {'model':model,'agent':{'max_turns':20,'disabled_toolsets':DISABLED},
            'platform_toolsets':{name:['skills','qarevin'] for name in ('cli','telegram','api_server')},
            'gateway':{'allow_all_users':False,'trust_env':False,'strict':True},
            'memory':{'memory_enabled':False,'user_profile_enabled':False},
            'mcp_servers':{'qarevin':{'command':'/opt/hermes/.venv/bin/python',
                'args':['-m','qarevin_tools.mcp_server'],
                'env':{'PYTHONPATH':'/opt/qarevin','QAREVIN_API_URL':api_url,
                       'QAREVIN_AGENT_TOKEN_FILE':'/run/secrets/qarevin_agent_token'},
                'timeout':30,'connect_timeout':15,'tools':{'resources':False,'prompts':False}}}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base',type=Path,required=True)
    parser.add_argument('--home',type=Path,default=Path.home()/'.hermes-qarevin')
    parser.add_argument('--api-url',default='http://qarevin-api:8000')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    result=configuration(yaml.safe_load(args.base.read_text()),args.api_url)
    if args.dry_run:
        print(json.dumps({'valid':True,'model':result['model'],'disabled_toolsets':DISABLED}))
        return
    if args.home.is_symlink() or (args.home/'config.yaml').exists():
        raise SystemExit('refusing to replace existing or symlinked profile; choose a fresh --home')
    args.home.mkdir(parents=True,exist_ok=True,mode=0o700)
    (args.home/'config.yaml').write_text(json.dumps(result,indent=2))
    (args.home/'config.yaml').chmod(0o600)
    (args.home/'SOUL.md').write_text((ROOT/'SOUL.md').read_text())
    target=args.home/'skills/quant-research'
    target.mkdir(parents=True,exist_ok=True)
    (target/'SKILL.md').write_text((ROOT/'skills/quant-research/SKILL.md').read_text())
    print('Created isolated Qarevin profile; configure model/Telegram credentials privately before starting.')


if __name__=='__main__':
    main()
