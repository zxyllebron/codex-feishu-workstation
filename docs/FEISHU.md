# Your Feishu account: application, permissions and sync

[中文](FEISHU.zh-CN.md) · [Official CLI](https://github.com/larksuite/cli)

## Which account is used?

You need your own Feishu account and an application that your tenant allows to obtain **user** authorization. A bot's membership in a group does not let it read all of your personal chats. The normal collection path here uses a user token; optional notifications use the same app's bot identity and are a separate capability. Ripple/回响 is not required, and no existing bridge account is borrowed.

The application cannot bypass tenant approval, message visibility, retention rules or scopes. A personal account/tenant may not expose every capability. If the required message scopes cannot be enabled, collection is unavailable for that app until its administrator approves an appropriate access path. Do not substitute a bot token and claim full personal coverage.

## 1. Install the official CLI

```bash
npx @larksuite/cli@latest install
lark-cli --version
python3 manage.py init
```

The implementation was checked against Feishu CLI **1.0.88**. Later versions may change setup fields or output; inspect that version's `--help` when troubleshooting. Official [installation/authentication reference](https://github.com/larksuite/cli#installation--quick-start).

## 2. Create an app or connect an existing one

```bash
python3 manage.py feishu-setup
```

This wraps the official `config init` with an isolated configuration environment. Follow the interactive prompts to create an app or use an existing App ID and App Secret. Complete any application-creation or availability approval in the browser. For an explicitly new app you can also run:

```bash
python3 manage.py feishu config init --new
```

For a manually managed enterprise app, open [Feishu Developer Console](https://open.feishu.cn/app), create/select the application for your own organization, set its availability to include your user, enable the user scopes below, and publish/apply the change through the tenant's process. Configure it with the same helper. An app being created is separate from the user granting it access.

`manage.py feishu ...` passes arguments to the official CLI. You can use its `config init --app-id ... --app-secret-stdin` path to provide a secret through stdin rather than a process-list argument; check `python3 manage.py feishu config init --help`. Do not store an App Secret in `config.json`, a shell history line, documentation or GitHub.

All helpers and the web process use `<data_dir>/feishu-cli` by default. If you select `feishu_cli_dir`, use that same path everywhere. Credentials/tokens are managed by the official CLI (its local store and, where applicable, the OS credential store). Running plain `lark-cli auth login` under another environment may log in a different store and will not configure this workbench.

## 3. Enable and grant only the required user scopes

| Scope | Workbench use |
|---|---|
| `offline_access` | Keep user authorization renewable where Feishu supports it |
| `search:message` | Cross-chat message search |
| `im:chat:readonly` | Read conversation metadata |
| `im:message:readonly` | Read message content |
| `im:message.group_msg:get_as_user` | Read authorized group messages as the user |
| `im:message.p2p_msg:get_as_user` | Read authorized private messages as the user |

```bash
python3 manage.py feishu-login
python3 manage.py feishu-status
python3 manage.py feishu auth check --scope "search:message im:chat:readonly im:message:readonly im:message.group_msg:get_as_user im:message.p2p_msg:get_as_user" --json
```

The login helper requests the exact six scopes; it does not request a broad domain grant. Review the browser consent screen and complete it yourself. Leave unrelated permissions disabled. Tenant approval may still be required. The web page's “connect personal Feishu” button can initiate/repeat user authorization after app credentials exist; it does not install the CLI or configure App Secrets.

After a successful helper setup/login, restart a running workbench to discard stale connection state. Open “记忆与消息 → 飞书消息”, refresh/check the connection, and start a collection. `ready=true, mode=user, phase=ready` means authorization checks passed. Only a completed job with no errors/pending work establishes that traversal of that range succeeded.

## 4. What the collector actually reads

The user adapter allows exactly:

```text
POST /open-apis/im/v1/messages/search
GET  /open-apis/im/v1/messages/mget
POST /open-apis/im/v1/chats/batch_query
GET  /open-apis/authen/v1/user_info
```

It searches a bounded time range across accessible conversations, follows page tokens, retrieves up to 50 message bodies per batch, verifies IDs, and enriches chat metadata. It preserves message IDs, timestamps, sender identity, thread IDs and reply relationships. It advances the cursor only after the batch is complete; missing bodies/errors/cursor loops are not marked complete. It can discover new replies inside older topics through the time-range search.

Plain/rich text and text-bearing cards are normalized. Images/audio/video/files are represented by metadata/placeholders; their content is not downloaded or understood. Deleted/withdrawn messages, API retention/index limits, forwarded submessages, or policy restrictions can leave gaps. “All visible history” means what the authorized API can return, not an unrestricted account backup. See the official [search implementation](https://github.com/larksuite/cli/blob/main/shortcuts/im/im_messages_search.go).

Automatic sync refreshes **today** every 10 minutes; manually choose a wider range to backfill earlier days. The UI always displays only today and four preceding dates, while older collected data remains in Markdown/SQLite. Pause stops collection and is respected by subsequent automatic checks. Resume keeps the existing range boundary and page progress; start a fresh job for newer messages beyond that boundary.

## 5. Optional reminders to yourself

Leave “飞书提醒” off for a completely read-only Feishu workflow. To enable reminders, the app needs a bot capability, **application** permission `im:message:send_as_bot`, and availability for your user. Publish/approve that capability as required. Open the bot's personal conversation in Feishu once if your tenant requires activation.

Enable the checkbox in Settings, then explicitly click the test button. The backend fetches the current authorized user's identity and sends as the bot **only to that user's `open_id`**. It never accepts a group target or arbitrary chat ID. Failure remains visible in the notification center. This optional write permission is not required for collecting messages and is not part of the user login scope list.

## 6. Revoke or switch accounts

```bash
python3 manage.py feishu auth logout
```

Revoke the application in Feishu's authorized-app management if needed. To use another application/account, rerun setup and login. Successful setup/login clears cached identity/chat metadata; restart the workbench as well. Existing collected records remain local unless you deliberately remove them; do not reuse one personal data directory for different people. Each user should have their own clone/configuration and data/credential stores.

## Troubleshooting

- CLI not found: set `lark_bin` to its executable path and restart.
- Logged in in terminal but not web: use the helper's isolated store, same OS user, same `WORKSTATION_CONFIG`, same keychain session.
- Missing scopes/permission denied: confirm both app-enabled scopes and actual user consent; wait for tenant approval and authorize again.
- Expired/revoked token: log in again. Do not continually restart collection against failed authorization.
- Job `partial/error`: inspect its errors and resume rather than declaring all messages collected.
- No new messages: check time range, cutoff, pause state, visibility and API index delay.
- Reminder failure: verify bot/application permission and user availability; collection can still succeed independently.
- Browser fallback: [FEISHU_BROWSER.md](../FEISHU_BROWSER.md) describes an optional authorized external browser worker. It is not an embedded browser, automatic scraper or substitute for tenant permissions.
