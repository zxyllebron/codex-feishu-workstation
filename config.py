"""Portable, non-secret configuration. CLI credentials stay in their own stores."""
import json
import os
import shutil
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = Path(os.environ.get('WORKSTATION_CONFIG', str(ROOT / 'config.json'))).expanduser().resolve()
DEFAULTS = {
    'name': '朋友', 'timezone': 'Asia/Shanghai', 'port': 8765,
    'data_dir': './data', 'codex_home': '~/.codex',
    'codex_bin': 'codex', 'codex_model': '', 'lark_bin': 'lark-cli',
    'feishu_cli_dir': '', 'codex_enabled': True, 'feishu_enabled': True,
    'read_codex_memories': True, 'excluded_thread_ids': [],
    'morning': '09:00', 'evening': '17:00', 'schedule_enabled': True,
    'gmail_enabled': False, 'applications_enabled': False, 'application_roots': [],
    'connector_inbox': './data/connector-inbox',
    'codex_transport': 'default',
}
SETTINGS = {**DEFAULTS, **(json.loads(CONFIG_FILE.read_text(encoding='utf-8-sig')) if CONFIG_FILE.exists() else {})}
ZoneInfo(SETTINGS['timezone'])  # Fail early on an invalid timezone.
if not isinstance(SETTINGS['port'], int) or not 1 <= SETTINGS['port'] <= 65535:
    raise ValueError('port must be an integer between 1 and 65535')

def path(value):
    p = Path(value).expanduser()
    return (CONFIG_FILE.parent / p).resolve() if not p.is_absolute() else p.resolve()

def executable(key):
    value = SETTINGS[key]
    return shutil.which(value) or str(Path(value).expanduser())

def codex_env():
    return {**os.environ, 'CODEX_HOME': str(path(SETTINGS['codex_home']))}

def feishu_env(data_dir):
    env = os.environ.copy()
    # Never inherit another agent/bridge's app, policy, profile, or token store.
    for key in list(env):
        if key.startswith(('LARK_', 'LARKSUITE_')) or key in ('OPENCLAW_HOME', 'HERMES_HOME'):
            env.pop(key, None)
    folder = path(SETTINGS['feishu_cli_dir']) if SETTINGS['feishu_cli_dir'] else Path(data_dir) / 'feishu-cli'
    folder.mkdir(parents=True, mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    env['LARKSUITE_CLI_CONFIG_DIR'] = str(folder)
    return env
