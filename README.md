# Codex × Feishu Workstation

English | [简体中文](README.zh-CN.md)

**A local personal workspace powered by Codex and your own Feishu account.** A clean, editable web UI for manual todos, inferred intentions, night-work recommendations, forecasts, and searchable memories/messages.

[Setup and Codex configuration](docs/SETUP.md) · [Feishu configuration](docs/FEISHU.md)

![Workstation UI — fictional demo data](docs/assets/overview.jpg)

## Try the UI immediately

Python **3.11+**, Linux/macOS or Windows through WSL2. No Python packages, frontend build, API keys, or accounts are required for the demo.

```bash
git clone https://github.com/zxyllebron/codex-feishu-workstation.git
cd codex-feishu-workstation
python3 server.py --demo
```

Open **http://127.0.0.1:8765/**. If occupied, add `--port 8766`. The demo uses fictional data in a temporary folder; it never connects to Feishu, reads your Codex history, or invokes a model. Edits disappear when the demo exits. Stop with Ctrl+C.

## Connect your own accounts

Install and sign in to **Codex CLI** and install the **official Feishu CLI** first. Account access and Feishu tenant approval are required; cloning this repository does not include anyone else's authorization.

```bash
npm install -g @openai/codex
codex login
npx @larksuite/cli@latest install

python3 manage.py init
# Edit config.json: display name, timezone, paths, optional Codex model.
python3 manage.py doctor
python3 manage.py feishu-setup
python3 manage.py feishu-login
python3 server.py
```

Complete Feishu application setup and the personal read-only permission grant in your browser. See the [step-by-step Feishu guide](docs/FEISHU.md), including exact scopes, new/existing app paths, optional private reminders, revocation, and troubleshooting. Every `manage.py feishu*` command uses the same isolated credential directory as the web service.

## What it does

- **Your todos stay yours.** Only manually entered tasks become todos. Codex proposes at most three intentions in a separate section.
- **17:00 planning.** Night recommendations (0–3) and forecasts (0–2) update together at 17:00, or when you explicitly click a planning button. Morning summaries at 09:00 update intentions only. Times can be changed or paused.
- **Manual execution.** A night recommendation contains its theme, content, and copyable prompt. You choose whether to paste it into Codex. Copying never marks it complete; checkboxes do. No automatic night execution or task queue.
- **Separate deletion and completion.** Todos, intentions, recommendations, and forecasts support right-click deletion. Completed work has separate lazy-loaded categories and a confirmed permanent-delete action.
- **Read-only ingestion.** Personal Feishu OAuth, cross-chat search, paginated bulk message retrieval, and thread/reply identifiers. Refreshes today's visible messages every 10 minutes. A bot alone does not grant access to your personal conversations.
- **Five-day window, long-term files.** The UI shows today plus the previous four dates. Older collected records remain in local SQLite and daily Markdown archives. A “related to me” filter selects mentions, DMs, your messages, and participated threads.
- **Reusable UI and backend.** Vanilla HTML/CSS/JavaScript, Python standard library, SQLite. Change CSS tokens, components, prompt schemas, or source adapters directly. No hosted dashboard subscription.

## Configuration and platform scope

`config.example.json` documents the non-secret settings. Copy/init it as `config.json`; credentials belong to the official CLIs, never this file. Relative paths resolve next to the selected configuration file. Set `WORKSTATION_CONFIG` to use another file. [Full configuration and Codex guide](docs/SETUP.md).

The current release supports **Codex + Feishu only**. The interface is Chinese; the project introduction and setup guides are available in Chinese and English. Linux is the tested runtime. macOS can run the foreground server; native Windows is not verified—use WSL2. Linux user-service installation is optional:

```bash
python3 manage.py install-service
# Run the two systemctl commands printed by the helper.
```

The app runs only on `127.0.0.1`; no public hosting or GitHub Pages backend is provided. Your computer and service must remain on for synchronization and schedules. No Codex desktop heartbeat is installed automatically.

## Data and privacy

Local files stay under the configured data directory. When you request or schedule analysis, selected Feishu messages and Codex history excerpts are sent through your authenticated Codex model service. **Local storage does not mean offline inference.** Read [data boundaries and limitations](SECURITY.md) before connecting workplace accounts.

This repository contains source, synthetic test/demo data, and documentation only. It does not contain the author's messages, local databases, private Feishu account/conversation identifiers, tokens, screenshots of private work, or Codex authentication files. Never publish your own `data/`, `config.json`, CLI credential stores, or `~/.codex`.

See the [release privacy audit](docs/RELEASE-PRIVACY.md) for the included/excluded files and public attribution boundary.

## Development

```bash
python3 -m unittest discover -s tests -q
node tests/test_browser_collector.mjs
node --check static/app.js
python3 scripts/smoke_demo.py
python3 scripts/audit_release.py
```

See [architecture, customization and API](docs/ARCHITECTURE.md). Contributions should keep personal ingestion read-only and night work user-controlled. [MIT license](LICENSE). This independent project is not affiliated with or endorsed by OpenAI or Feishu; the UI uses system fonts and original HTML/CSS, without proprietary logos or font files.
