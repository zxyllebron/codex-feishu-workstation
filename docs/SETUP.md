# Installation and Codex configuration

[中文](SETUP.zh-CN.md) · [Feishu guide](FEISHU.md)

## 1. Requirements and files

Use Python 3.11+ with SQLite and IANA timezone data. Linux is tested; macOS foreground use is supported by the code but not release-tested. On Windows use a Linux WSL2 distribution. Node.js 20+ is recommended for installing the external CLIs. The server itself has no Python third-party dependencies or Node runtime dependency.

Clone or extract a release, open a terminal in that folder, then run:

```bash
python3 server.py --demo --port 8766
```

This is a disposable account-free UI preview. Close it before starting the real instance on the same port.

## 2. Install and authenticate Codex

Install the official CLI and authenticate **as the OS user that will run the workbench**:

```bash
npm install -g @openai/codex
codex --version
codex login
codex login status
```

Complete the browser sign-in. Alternatively, with an OpenAI API key already in the environment, use `printenv OPENAI_API_KEY | codex login --with-api-key`. API-key usage is billed to that API account. Never put a credential in a repository file. Official references: [CLI](https://learn.chatgpt.com/docs/codex/cli), [authentication](https://learn.chatgpt.com/docs/auth).

The workbench invokes `codex exec --ephemeral --skip-git-repo-check --sandbox read-only --output-schema ... -o ... -`. Selected source material is passed through stdin, the final JSON is written to a local run folder, and saved CLI authentication is reused. The workbench never opens or exports `auth.json`. See [non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode).

## 3. Initialize configuration

```bash
python3 manage.py init
python3 manage.py doctor
```

Edit the generated `config.json`. It is ignored by Git and is not a credential store.

| Key | Default | Meaning |
|---|---|---|
| `name` | `朋友` | Initial UI name; later change it in Settings |
| `timezone` | `Asia/Shanghai` | IANA timezone for dates, schedules and five-day retention window |
| `port` | `8765` | Loopback HTTP port; `server.py --port` overrides it for that process |
| `data_dir` | `./data` | SQLite, Markdown, exports and run logs |
| `codex_home` | `~/.codex` | CLI account/config and local history directory |
| `codex_bin` | `codex` | CLI executable on PATH, or an absolute path |
| `codex_model` | empty | Uses your CLI's default; set an OpenAI model your account can access to pass `--model` |
| `lark_bin` | `lark-cli` | Official Feishu CLI executable |
| `feishu_cli_dir` | empty | Empty selects `<data_dir>/feishu-cli`; otherwise use your dedicated CLI store |
| `codex_enabled` | `true` | Automatic Codex history collection; does not disable explicit analysis |
| `feishu_enabled` | `true` | Feishu account checks and synchronization |
| `read_codex_memories` | `true` | Read available local Codex memory database outputs |
| `excluded_thread_ids` | `[]` | Chat IDs to exclude from Codex ingestion |
| `morning` / `evening` | `09:00` / `17:00` | Initial schedule values; later edit them in the UI |
| `schedule_enabled` | `true` | Initial daily scheduling preference; can be paused in the UI |

Relative paths resolve beside `config.json`, not the shell's working directory. Use `WORKSTATION_CONFIG=/absolute/path/config.json python3 server.py` for an alternative file. Do not rename `HOME` or `CODEX_HOME` in shell scripts to use them as temporary variables. The app sets the Codex subprocess's `CODEX_HOME` to the configured `codex_home`.

Name and schedule values seed a new data directory. Once initialized, their current values are stored in SQLite and changed through Settings; editing the initial defaults does not overwrite existing preferences. Configuration-file changes require restarting your instance. The UI refreshes live data periodically.

If `codex` or `lark-cli` is installed through nvm or another version manager, `doctor` must find it under the same PATH used by the background service. Set the executable fields to explicit paths when needed. The service helper captures your current PATH.

For a dedicated Codex account/configuration store, choose another `codex_home`, sign in to it with `CODEX_HOME=/your/dedicated/folder codex login`, and leave unneeded MCP servers/plugins unconfigured. History in another Codex directory will not be collected by that isolated instance. This release does not configure other model providers.

## 4. History and memory compatibility

The reader opens available `state_*.sqlite` databases in read-only mode and checks the thread fields it needs; when no thread database exists, it can discover session metadata from `sessions/**/*.jsonl`. It selects recent user requests, final results and limited commentary, not chain-of-thought or tool output. The UI lists recent five-day records, while planning can consider seven days of active Codex chats.

Memory ingestion reads supported `memories_*.sqlite` stage-one outputs if present. A new installation may have no memory database; that is valid and does not prevent Feishu or manual todos from working. These are local Codex implementation formats, not a stable public API. Unsupported formats must be reported as limited coverage, never as a complete history import. A missing CLI executable does not stop the UI from opening, but analysis will fail until configured.

## 5. Connect Feishu and run

Follow [FEISHU.md](FEISHU.md). Then:

```bash
python3 server.py
```

Visit the displayed loopback URL. `GET /api/health` confirms HTTP health; `/api/state` contains actual sync, scheduler, report and error status. Account setup success is separate from message-collection success.

## 6. Optional Linux background service

```bash
python3 manage.py install-service
systemctl --user daemon-reload
systemctl --user enable --now codex-feishu-workstation.service
systemctl --user status codex-feishu-workstation.service
```

The helper generates a user unit from your actual folder, interpreter, configuration file and PATH. It does not install or change the author's service. It refuses to overwrite an existing unit. Inspect the generated file under `~/.config/systemd/user/` before enabling it.

```bash
journalctl --user -u codex-feishu-workstation.service -n 50 --no-pager
systemctl --user restart codex-feishu-workstation.service
systemctl --user stop codex-feishu-workstation.service
```

User services normally start after login. Keep the computer awake; suspended/offline machines cannot run schedules. Planning starts only in the configured minute and is not caught up later. Morning summaries can catch up within one hour. A restart does not rerun a schedule already recorded for that date. No 08:00/20:00 Codex monitor is installed by this repository; monitoring is optional and separate from these schedules.

On macOS, run the foreground server or create your own launchd entry. No unverified launchd or Windows-service installer is shipped.

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| Port already used | Choose another `port` / `--port`; do not stop unrelated services |
| Analysis fails | `codex login status`, executable path, account model access, network, local `data/runs/<id>/execution.log` |
| Empty history | Correct `codex_home`, history exists, supported schema, excluded IDs and date window |
| Empty memories | A fresh CLI may have none; this is optional |
| Works in terminal, fails as service | Interpreter, captured PATH, home directory, CLI keychain access in the user session |
| Timezone not found | Install OS timezone data (`tzdata` on many Linux distributions) |
| Scheduled report missing | Computer awake, service enabled, Settings enabled, schedule fires/report status; click manually if the planning minute was missed |
| Feishu authorization or message error | [Feishu troubleshooting](FEISHU.md#troubleshooting) |

Do not send private run logs, database files or account exports in a public issue.
