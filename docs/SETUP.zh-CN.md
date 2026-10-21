# 安装与 Codex 配置

[English](SETUP.md) · [飞书配置](FEISHU.zh-CN.md)

## 1. 环境与演示

需要 Python 3.11+（含 SQLite 和时区数据）。Linux、macOS、原生 Windows 可前台运行，自动检查使用虚构数据和模拟账号。先运行 `python3 -m pip install -r requirements.txt`，仅 Windows 会安装 `tzdata`。Windows 将命令中的 `python3` 换成 `python`。Node.js 用于安装外部 CLI，网页服务不需要 Node 或前端构建。

下载仓库后在目录内运行：

```bash
python3 server.py --demo --port 8766
```

访问终端输出的网址即可体验。该模式使用临时虚构数据，关闭后不留存，不连接账号。正式使用前停止同端口的演示。

## 2. 安装和登录 Codex

使用与运行工作台相同的系统用户执行：

```bash
npm install -g @openai/codex
codex --version
codex login
codex login status
```

在浏览器中完成自己的登录。如果选择 OpenAI API Key，可在已设置 `OPENAI_API_KEY` 的终端运行 `printenv OPENAI_API_KEY | codex login --with-api-key`；API Key 调用计入对应 API 账号费用。不要将密钥放进仓库。[官方 CLI 说明](https://learn.chatgpt.com/docs/codex/cli)、[官方认证说明](https://learn.chatgpt.com/docs/auth)。

工作台通过 `codex exec` 的临时会话、只读沙箱及 JSON Schema 整理选取材料，输入走 stdin，结果和诊断日志保存在本机的运行目录。沿用 CLI 登录，不读取或导出 `auth.json` 的内容。[官方非交互模式](https://learn.chatgpt.com/docs/non-interactive-mode)。

## 3. 配置工作台

```bash
python3 manage.py init
python3 manage.py doctor
```

生成的 `config.json` 已被 Git 忽略。它只放配置，不放账号密码或 token。

飞书可选：设 `feishu_enabled: false` 后无需安装飞书 CLI。申请模式可使用 [config.applications.example.json](../config.applications.example.json) 作为新实例配置，按 [申请快照教程](APPLICATIONS.md) 设置自己的目录与采集器。不要覆盖已有个人配置。`applications_enabled` 开启申请页；`gmail_enabled` 仅表示启用 Gmail 证据展示，不会自动登录或读取邮箱。`application_roots` 默认为空；`connector_inbox` 默认 `./data/connector-inbox`。不安装作者的连接器授权或 Codex 定时巡检。

执行使用 `--ignore-user-config`，请用 `codex exec --help` 确认版本支持。账号沿用自己的登录，模型通过 `codex_model` 显式设置。`codex_transport` 默认 `default`，需要固定 HTTPS 通道时可设 `https`。应用仍会将选取证据发送给模型服务。

| 配置项 | 默认值 | 作用 |
|---|---|---|
| `name` | `朋友` | 首次初始化的称呼，以后在网页设置中修改 |
| `timezone` | `Asia/Shanghai` | 日期、计划时间与近五天展示使用的 IANA 时区 |
| `port` | `8765` | 本机端口；启动参数 `--port` 可临时覆盖 |
| `data_dir` | `./data` | SQLite、归档、导出、运行日志的存储位置 |
| `codex_home` | `~/.codex` | 你的 Codex 账号配置与历史记录目录 |
| `codex_bin` | `codex` | PATH 中的可执行文件名，也可填绝对路径 |
| `codex_model` | 空 | 默认使用 CLI 的模型配置；填写自己账号可用的 OpenAI 模型名后会传入 `--model` |
| `lark_bin` | `lark-cli` | 飞书官方 CLI 路径 |
| `feishu_cli_dir` | 空 | 默认独立保存在 `<data_dir>/feishu-cli`；也可指定专用 CLI 配置目录 |
| `codex_enabled` | `true` | 是否自动采集 Codex 历史；不禁用用户主动点击的整理 |
| `feishu_enabled` | `true` | 是否检查飞书账号并同步 |
| `read_codex_memories` | `true` | 是否读取存在且格式兼容的本地 Codex 记忆库 |
| `excluded_thread_ids` | `[]` | 不纳入整理的 Codex 会话 ID 列表 |
| `morning` / `evening` | `09:00` / `17:00` | 首次初始化的晨报、推荐与预判时间 |
| `schedule_enabled` | `true` | 首次初始化是否启用计划，可在网页中暂停 |

相对路径以配置文件所在目录为基准。另选配置文件可运行 `WORKSTATION_CONFIG=/绝对路径/config.json python3 server.py`。程序为 Codex 子进程设置配置中的 `codex_home`，不会为了运行本项目改写你的全局账号配置。

称呼、计划时间和计划开关只用于初始化新数据目录；已有实例的当前值存储在 SQLite，请在网页设置中修改。其他配置文件调整后重启自己的服务。

通过 nvm 等工具安装的 CLI 可能不在后台服务 PATH 中。先确保 `doctor` 能找到；必要时把两个 `*_bin` 改成绝对路径。服务安装助手会保留安装时的 PATH。

需要隔离账号和工具配置时，可为 `codex_home` 单独指定目录，再用 `CODEX_HOME=/专用目录 codex login` 登录，保持该目录不配置额外 MCP/插件。这种隔离实例不会自动读取其他 Codex 目录的历史。本版不配置其他 AI 服务商。

## 4. Codex 历史与记忆兼容性

读取器以只读方式打开 `state_*.sqlite` 中兼容的线程表；没有线程数据库时，可从 `sessions/**/*.jsonl` 的会话元信息发现历史。只选取近期用户需求、最终结果和少量过程说明，不收集内部思考或工具输出。网页展示近五天，整理可参考最近七天活跃会话。

记忆读取支持可用的 `memories_*.sqlite` 初级摘要。新账号没有记忆库很正常，不影响待办和飞书功能。这些是 Codex 的本地实现格式，并非永久稳定的公开接口；格式不兼容时只能报告覆盖受限，不能宣称完整导入。CLI 尚未安装时也能打开 UI，但不能成功调用整理。

## 5. 飞书和正式启动

按 [飞书配置](FEISHU.zh-CN.md) 完成自己的应用及用户授权，然后运行：

```bash
python3 server.py
```

访问终端输出的网址。`/api/health` 验证 HTTP 服务，`/api/state` 包含真实同步状态、调度、报告和错误。账号授权完成不等于消息遍历已经完成。

## 6. Linux 可选后台服务

```bash
python3 manage.py install-service
systemctl --user daemon-reload
systemctl --user enable --now codex-feishu-workstation.service
systemctl --user status codex-feishu-workstation.service
```

助手根据你的真实目录、Python 路径、配置文件和 PATH 生成用户服务，不操作作者原有服务；同名服务存在时拒绝覆盖。可先查看 `~/.config/systemd/user/codex-feishu-workstation.service`。

```bash
journalctl --user -u codex-feishu-workstation.service -n 50 --no-pager
systemctl --user restart codex-feishu-workstation.service
systemctl --user stop codex-feishu-workstation.service
```

默认用户登录后启动，电脑须开机且不休眠。推荐与预判只在指定分钟启动，错过后不补跑；晨报允许一小时内补跑。同一天已有调度记录不因重启而重复执行。仓库不会为你创建 08:00/20:00 的 Codex 巡检，这与网页自身的晨报和推荐是两套机制。

macOS 可前台运行或自行配置 launchd；本版不提供未经验证的 macOS/Windows 服务安装器。

## 7. 常见问题

- 端口被占：选择新端口，不要停止无关服务。
- 整理失败：检查 CLI 路径、`codex login status`、模型权限、网络及本机 `data/runs/<id>/execution.log`。
- 没有历史：检查 `codex_home`、本机是否已有聊天记录、数据格式、时间范围和排除列表。
- 没有记忆：新账号可能尚未生成，属于可选来源。
- 终端正常、服务失败：检查服务中的 Python、PATH、登录用户及系统钥匙串是否可用。
- 找不到时区：安装系统时区包，常见 Linux 发行版为 `tzdata`。
- 定时未执行：查看网页是否暂停计划、电脑是否休眠及调度结果；错过推荐时段请手动点击。
- 飞书问题：见 [飞书故障排查](FEISHU.zh-CN.md#故障排查)。

公开 issue 不要附上私人日志、数据库或账号导出文件。
