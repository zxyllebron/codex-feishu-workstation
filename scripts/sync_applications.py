"""Import private read-only snapshots and refresh application evidence."""
import argparse
import json
from pathlib import Path
import sys
import urllib.request
import urllib.error
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import applications
import storage as db

parser=argparse.ArgumentParser()
parser.add_argument('--connector-file',type=Path)
parser.add_argument('--reconcile',action='store_true')
args=parser.parse_args()
if not (db.DATA/'workstation.sqlite').is_file():db.init()
if args.connector_file:
    print(json.dumps({'imported':applications.import_connector(json.loads(args.connector_file.read_text(encoding='utf-8')))},ensure_ascii=False))
print(json.dumps({'sync':applications.sync_local()},ensure_ascii=False))
if args.reconcile:
    import config
    base='http://127.0.0.1:'+str(config.SETTINGS['port'])
    try:
        with urllib.request.urlopen(base+'/api/state',timeout=3) as response:state=json.load(response)
    except (OSError,ValueError):state=None
    if state:
        request=urllib.request.Request(base+'/api/applications/reconcile',data=b'{}',
            headers={'Content-Type':'application/json','X-Workstation-Key':state['csrf'],'Origin':base})
        with urllib.request.urlopen(request,timeout=5) as response:print(json.dumps(json.load(response)))
    else:
        result=applications.reconcile()
        print(json.dumps({'applications':len(result.get('items',[])),'contacts':len(result.get('contacts',[])),
                          'error':result.get('error'),'generated_at':result.get('generated_at')},ensure_ascii=False))
        if result.get('error'):raise SystemExit(1)
