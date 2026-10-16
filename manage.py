#!/usr/bin/env python3
"""Setup helpers; never accepts or prints a credential in a command argument."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import config
import storage as db

def main():
    parser=argparse.ArgumentParser(description='Workstation setup / 安装配置')
    parser.add_argument('command',choices=['init','doctor','feishu-setup','feishu-login','feishu-status','feishu','install-service'])
    parser.add_argument('args',nargs=argparse.REMAINDER)
    args=parser.parse_args()
    if args.command=='init':
        if config.CONFIG_FILE.exists():print('Existing config preserved / 保留已有配置:',config.CONFIG_FILE);return
        config.CONFIG_FILE.parent.mkdir(parents=True,exist_ok=True)
        with config.CONFIG_FILE.open('x') as f:json.dump(config.DEFAULTS,f,ensure_ascii=False,indent=2);f.write('\n')
        config.CONFIG_FILE.chmod(0o600);print('Created / 已生成:',config.CONFIG_FILE);return
    if args.command=='doctor':
        checks=[]
        for key in ('codex_bin','lark_bin'):
            exe=config.executable(key);found=bool(shutil.which(exe))
            checks.append({'check':key,'ok':found,'path':exe})
        checks += [{'check':'python >= 3.11','ok':sys.version_info>=(3,11)},
                   {'check':'codex_home exists (history optional)','ok':config.path(config.SETTINGS['codex_home']).exists()},
                   {'check':'timezone','ok':True,'value':config.SETTINGS['timezone']}]
        print(json.dumps(checks,ensure_ascii=False,indent=2));return
    if args.command=='install-service':
        if not sys.platform.startswith('linux'):raise SystemExit('The helper requires Linux + systemd. Run python3 server.py in a terminal on macOS.')
        unit=Path.home()/'.config/systemd/user/codex-feishu-workstation.service'
        if unit.exists():raise SystemExit('Service already exists; review/edit it manually: '+str(unit))
        def quote(s):
            if '\n' in s or '\r' in s:raise ValueError('Newlines not allowed in unit values')
            return '"'+s.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
        content='\n'.join(['[Unit]','Description=Codex Feishu Workstation','After=network-online.target','','[Service]',
            'Type=simple','WorkingDirectory='+quote(str(config.ROOT)),
            'ExecStart='+quote(sys.executable)+' '+quote(str(config.ROOT/'server.py')),
            'Environment='+quote('PATH='+os.environ.get('PATH','/usr/local/bin:/usr/bin:/bin')),
            'Environment='+quote('WORKSTATION_CONFIG='+str(config.CONFIG_FILE)),
            'Environment=PYTHONUNBUFFERED=1','UMask=0077','Restart=on-failure','RestartSec=5','TimeoutStopSec=15','KillMode=control-group',
            '','[Install]','WantedBy=default.target',''])
        unit.parent.mkdir(parents=True,exist_ok=True);unit.write_text(content);unit.chmod(0o600)
        print('Created / 已生成:',unit)
        print('systemctl --user daemon-reload\nsystemctl --user enable --now codex-feishu-workstation.service');return
    commands={'feishu-setup':['config','init'],'feishu-status':['auth','status']}
    if args.command=='feishu-login':
        from feishu import SCOPES
        command=['auth','login','--scope',' '.join(SCOPES)]
    else:command=commands.get(args.command,args.args)
    if not command:raise SystemExit('Usage: python3 manage.py feishu <lark-cli arguments>')
    # CLI itself handles secret prompts and the browser authorization flow.
    result=subprocess.run([config.executable('lark_bin'),*command],env=config.feishu_env(db.DATA))
    if result.returncode==0 and args.command in ('feishu-login','feishu-setup'):
        db.init();db.put('feishu_connection',{});db.put('feishu_self',{});db.put('feishu_chat_cache',{})
    raise SystemExit(result.returncode)

if __name__=='__main__':main()
