#!/usr/bin/env python3
"""Offline integration check: a clean instance and disposable demo, no CLIs/accounts."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
ROOT=Path(__file__).resolve().parents[1]

def run(demo):
    with tempfile.TemporaryDirectory(prefix='workstation-smoke-') as td:
        folder=Path(td)
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        cfg={'port':port,'data_dir':str(folder/'data'),'codex_home':str(folder/'empty-codex'),
             'codex_enabled':False,'feishu_enabled':True if demo else False,'schedule_enabled':False}
        path=folder/'config.json';path.write_text(json.dumps(cfg))
        env={**os.environ,'WORKSTATION_CONFIG':str(path),'PATH':'/usr/bin:/bin'}
        log=(folder/'server.log').open('w')
        options={'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {}
        proc=subprocess.Popen([sys.executable,str(ROOT/'server.py'),*(['--demo'] if demo else [])],env=env,cwd=ROOT,stdout=log,stderr=log,**options)
        base=f'http://127.0.0.1:{port}'
        # This check is local-only; do not inherit system/CI HTTP proxies (including macOS settings).
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def get(route):
            with opener.open(base+route,timeout=2) as r:return json.load(r)
        try:
            deadline=time.monotonic()+20
            while True:
                try:
                    if get('/api/health')['ok']:break
                except (OSError,ValueError):
                    if proc.poll() is not None or time.monotonic()>deadline:
                        log.flush()
                        raise RuntimeError('Server did not become healthy; exit='+str(proc.poll())+'\n'+(folder/'server.log').read_text(encoding='utf-8',errors='replace'))
                    time.sleep(.1)
            state=get('/api/state');assert state['demo']==demo
            assert state['settings']['auto_night'] is False
            if demo:
                assert len(state['tasks'])==1 and len(state['night_tasks'])==1
                records=get('/api/records');assert all(r['id']!='memory:demo-old' for r in records['items'])
                assert len(get('/api/archives')['items'])==2
                req=urllib.request.Request(base+'/api/analyze',data=b'{}',headers={'X-Workstation-Key':state['csrf'],'Content-Type':'application/json'})
                try:opener.open(req,timeout=5);raise AssertionError('Demo analysis must not run')
                except urllib.error.HTTPError as e:assert e.code==400
            else:assert not state['tasks'] and not state['records'] and not state['night_tasks']
            print(('Account-free demo' if demo else 'Clean empty instance')+': HTTP smoke test passed')
        finally:
            if os.name=='nt' and proc.poll() is None:
                # Windows venv launchers may own a child interpreter that still holds the log.
                subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,check=False)
            elif proc.poll() is None:proc.terminate()
            try:proc.wait(timeout=5)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
            log.close()

if __name__=='__main__':run(False);run(True)
