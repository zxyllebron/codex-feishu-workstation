# Application tracking and Gmail snapshots

[README](../README.md) · [中文简介](../README.zh-CN.md) · [Setup](SETUP.md)

Mystation can group active applications by school, show programs and entry cycles, cite source evidence, and keep faculty correspondence separate. This optional adapter does not sign in to Gmail or application portals. Downloading this repository never grants access to the author's accounts or to a Codex connector.

## Enable it

For a new instance, copy [config.applications.example.json](../config.applications.example.json) to the ignored `config.json`; preserve your existing configuration if already set up. The example disables Feishu and daily planning. Install/authenticate Codex yourself, then set these fields:

| Field | Meaning |
|---|---|
| `applications_enabled` | Enable the navigation, evidence collection and explicit Codex reconciliation |
| `gmail_enabled` | Advertise optional Gmail evidence; this flag does not authenticate or fetch email |
| `application_roots` | Your own local notes folders; defaults to empty |
| `connector_inbox` | JSON snapshot folder, relative to the configuration file |
| `codex_home` | Your own Codex account/history directory |

Local Markdown discovery currently recognizes Chinese application-note filenames such as `申请状态.md`, `申请填写记录.md` and `申请进度.md`. Backup/account folders are skipped. Other languages or filename conventions can use the snapshot adapter, or change `NOTE` in `applications.py`. Recent final answers from supported application-related Codex sessions are historical evidence, not live portal checks.

## Supply your own authorized snapshots

An external authorized collector (for example, a connector available in your own Codex session) must actually read the email or signed-in portal first. Save only necessary evidence under `data/connector-inbox/`. Do not export a connector's grant, passwords, codes, tokens or signed login links.

The [fictional JSON example](examples/application-snapshot.json) shows the format:

- `records`: a list; `kind` is `gmail` or `portal`.
- `id`: stable source ID prefixed with `gmail:` or `portal:`; email IDs deduplicate repeated imports.
- `title`, `text`, `updated`: required. `updated` is the original source timestamp with an explicit timezone.
- Optional: `source_url`, `portal_url`, `thread_id`, `direction` (`sent` / `received`), `recipients`, `coverage`.
- `status.gmail` / `status.portals`: last real check time in `checked_at`, plus `state`, `coverage`, optional `error` / `account`. A status label alone does not verify an application.

Portal records must represent an actually read application status page. If the portal is inaccessible or signed out, keep it pending and do not create a fabricated verified record. Redaction is best effort: review snapshots before import. In particular, never place credentials in metadata or free-form coverage fields.

```bash
# Import a snapshot and refresh local evidence; no model call:
python3 scripts/sync_applications.py --connector-file /path/to/your-snapshot.json
# Read snapshots already in connector_inbox:
python3 scripts/sync_applications.py
# Explicitly reconcile evidence through your authenticated Codex:
python3 scripts/sync_applications.py --reconcile
```

If the server is running, `--reconcile` starts a background analysis. Wait until `/api/state` reports `busy: false` and check the latest run and `application_sync.dirty`; do not launch duplicate analyses. If no server is running, the helper runs reconciliation in the foreground. The interface's “Codex 核对进度” button does the same analysis. It does not fetch Gmail or browse portals.

The server refreshes configured local notes/history and inbox snapshots roughly every ten minutes. It does not install a scheduled Codex heartbeat. For incremental mail collection, overlap the last actual check window, deduplicate by message ID, and retain original email dates.

## Reading the tracker

Expand a school to see its programs. Click a program for source evidence, the current next action and any clean portal link. An account-registration email, advertisement, automatic reply or faculty inquiry is not evidence of formal submission or admission. “门户待核验” remains until an imported portal snapshot supplies actual evidence; even a verified snapshot is historical as of its displayed timestamp.

The model receives selected local evidence for reconciliation. It cannot submit applications, pay fees, send mail or invite referees through this adapter. Model stages and summaries can be wrong: verify consequential decisions against original evidence. Deleting data locally does not alter email or school systems.

## 中文使用摘要

申请模式使用自己的 `config.json`、本地材料目录与 Codex 登录。学校分组下展示具体项目；导师联系独立显示。Gmail 和门户没有内置登录，必须由你自己授权的采集器先读取，再导入脱敏快照。`updated` 保留邮件原日期，`checked_at` 只记真实核对时间；网页打不开、未登录时保留待核验。点击“Codex 核对进度”仅整理已有材料，不替你查邮箱或提交申请。所有真实数据只存本机，不要提交 `data/`、`config.json` 或账号凭据。
