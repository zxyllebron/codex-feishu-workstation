# Codex × 飞书个人工作台

[English](README.md) · [安装与 Codex 配置](docs/SETUP.zh-CN.md) · [飞书账号配置](docs/FEISHU.zh-CN.md)

一个在自己电脑上运行、由 Codex 驱动的个人网页工作台。保留文字侧边栏、白色主区域和简洁列表，将**工作概览、今日工作、夜间工作、明日预判、记忆与消息**放在同一处。你可以直接复用 UI 和 Python 后端，也可以按自己的习惯修改。

![工作台界面，全部为虚构演示数据](docs/assets/overview.png)

## 先体验界面

需要 Python **3.11 或以上**。Linux、macOS 可在终端启动，Windows 建议使用 WSL2。演示不需要账号、API Key、Python 第三方库或前端构建工具。

```bash
git clone https://github.com/zxyllebron/codex-feishu-workstation.git
cd codex-feishu-workstation
python3 server.py --demo
```

打开 **http://127.0.0.1:8765/**。端口占用时加 `--port 8766`。演示数据保存在临时目录，不读取真实 Codex 记录、不连接飞书、不调用模型；可以尝试新增、勾选、右键删除，退出后不保留。按 Ctrl+C 停止。

## 接入自己的账号

```bash
npm install -g @openai/codex
codex login
npx @larksuite/cli@latest install

python3 manage.py init
# 编辑 config.json：称呼、时区、程序路径和可选模型。
python3 manage.py doctor
python3 manage.py feishu-setup
python3 manage.py feishu-login
python3 server.py
```

必须使用**你自己的飞书应用和个人授权**。企业权限可能需要管理员审批，下载仓库不会自动获得个人消息访问权。飞书配置、精确权限清单、已有应用接入、只读采集原理和可选私人提醒详见 [飞书配置教程](docs/FEISHU.zh-CN.md)；Codex 登录、历史数据读取、后台服务和故障排查详见 [安装教程](docs/SETUP.zh-CN.md)。

## 功能与交互

- **手填待办**：只由用户自己创建，模型不代填。推测出的 0–3 项工作单独展示在“意向”，线索不足就留空。
- **17:00 统一规划**：夜间推荐与明日预判同时生成；其他时间只接受用户主动点击。09:00 晨报只整理意向。时间可在设置中修改或暂停，错过推荐时段不自动补跑。
- **夜间工作由你运行**：只提供主题、内容和完整提示词，你自行复制到 Codex 运行。没有夜间自动执行或任务队列；复制不算完成，手动勾选才进入“已完成”。
- **删除与完成分开**：待办、意向、夜间推荐、预判支持右键“删除”，不转入已完成；已完成按今日工作、夜间工作、日期分别查看，支持确认后完全删除。
- **个人飞书只读同步**：默认每 10 分钟同步当天授权可见消息，跨会话搜索后批量取正文，保留话题、回复关系、消息 ID 和分页进度。机器人自身不能代替个人消息授权。
- **近五天展示、历史持续留存**：网页仅展示今天及前四天；更早的采集内容保存在 SQLite 和按日期生成的 Markdown 中。“与我相关”支持 @ 本人、本人消息、私聊和参与话题等筛选。
- **便于定制**：HTML/CSS/JavaScript + Python 标准库 + SQLite，没有前端编译步骤。可以直接修改布局、配色、提示词和数据处理逻辑。

## 适配范围

当前只做 **Codex + 飞书**。UI 保持中文，项目介绍和安装配置文档提供中英双语。Linux 为已验证运行环境；macOS 支持前台启动，原生 Windows 尚未验证，请用 WSL2。可选安装 Linux 登录自启服务：

```bash
python3 manage.py install-service
# 按输出执行 systemctl 命令。
```

默认只监听 `127.0.0.1`。这是本机应用，GitHub 用于分发代码，不会把后端变成 GitHub Pages 网站。电脑和后台服务需保持运行；不自动创建 Codex 桌面定时巡检。

## 数据说明

仓库不包含作者的账号、会话 ID、聊天记录、数据库、登录凭据或私人工作截图。`config.json` 只存非敏感配置，账号凭据由官方 CLI 管理；`data/`、`config.json`、`~/.codex` 和飞书凭据目录不要上传。

**本机存储不等于离线推理**：整理时会把选取的飞书内容和 Codex 会话片段发送给你登录的 Codex 模型服务。连接企业账号前请确认你有权这样处理数据。边界和限制见 [SECURITY.md](SECURITY.md)。

## 开发与授权

```bash
python3 -m unittest discover -s tests -q
node tests/test_browser_collector.mjs
node --check static/app.js
python3 scripts/smoke_demo.py
python3 scripts/audit_release.py
```

配置示例见 [config.example.json](config.example.json)，实现结构和接口见 [架构说明](docs/ARCHITECTURE.md)。采用 [MIT 许可证](LICENSE)，允许复用框架和 UI。本项目独立开发，与 OpenAI、飞书无隶属或背书关系；使用系统字体，不包含专有字体或品牌标志素材。
