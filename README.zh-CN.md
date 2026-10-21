# Mystation · 个人工作台

[English](README.md) | 简体中文

[安装与 Codex 配置](docs/SETUP.zh-CN.md) · [申请进度与 Gmail 快照](docs/APPLICATIONS.md) · [可选飞书配置](docs/FEISHU.zh-CN.md)

一个在自己电脑上运行、由 Codex 驱动的个人网页工作台。将**工作概览、待办、申请进度、夜间推荐、记忆与消息**放在同一处，飞书可选。项目已从 Codex × 飞书工作台更名为 Mystation，仓库地址保持不变。UI 和 Python 后端均可复用。

![工作台界面，全部为虚构演示数据](docs/assets/overview.jpg)

## 先体验界面

需要 Python **3.11 或以上**。支持 Linux/macOS 前台启动；原生 Windows 先运行 `python -m pip install -r requirements.txt` 安装时区数据。演示不需要账号、API Key 或前端构建工具。

```bash
git clone https://github.com/zxyllebron/codex-feishu-workstation.git
cd codex-feishu-workstation
python3 server.py --demo
```

打开 **http://127.0.0.1:8765/**。Windows 将 `python3` 换成 `python`。端口占用时加 `--port 8766`。演示使用临时虚构数据，包含按学校分组的申请项目，不读取真实 Codex 记录、不连接账号、不调用模型；可尝试新增、勾选、编辑和回退。按 Ctrl+C 停止，演示修改不保留。

## 接入自己的账号

```bash
npm install -g @openai/codex
codex login

python3 manage.py init
# 编辑 config.json：称呼、时区、程序路径和可选模型。
python3 manage.py doctor
python3 server.py
```

编辑 `config.json`：不使用飞书时设 `feishu_enabled: false`。申请版可把 [config.applications.example.json](config.applications.example.json) 另存为 `config.json`，再填自己的路径。Gmail 不自带登录授权，需用本人授权的采集器导入快照，详见 [申请进度说明](docs/APPLICATIONS.md)。如使用飞书，安装 `npx @larksuite/cli@latest install`，执行 `python3 manage.py feishu-setup`、`python3 manage.py feishu-login`，按 [教程](docs/FEISHU.zh-CN.md) 完成自己的应用与个人授权。

## 功能与交互

- **手填待办**：只由用户自己创建，模型不代填。推测出的 0–3 项工作单独展示在“意向”，线索不足就留空。
- **右键编辑和回退**：手写待办右键可编辑内容；完成后仍可编辑，也可回退为未完成。仅编辑内容不重置完成时间。
- **完成后保留 24 小时**：首页展示最近完成的待办、意向和夜间推荐，满 24 小时后进入“记忆与消息 → 已完成”。跨午夜与重启不影响计时，回退后再次完成会重新计时。
- **按学校查看申请**：学校下折叠展示项目、阶段、下一步和证据，导师联系独立归类。可读本地填报记录、申请聊天和导入的 Gmail/门户快照；历史材料不冒充实时门户核验。
- **17:00 统一规划**：夜间推荐与明日预判同时生成；其他时间只接受用户主动点击。09:00 晨报只整理意向。时间可在设置中修改或暂停，错过推荐时段不自动补跑。
- **夜间工作由你运行**：只提供主题、内容和完整提示词，你自行复制到 Codex 运行。没有夜间自动执行或任务队列；复制不算完成，手动勾选才进入“已完成”。
- **删除与完成分开**：待办、意向、夜间推荐、预判支持右键“删除”，不转入已完成；已完成按今日工作、夜间工作、日期分别查看，支持确认后完全删除。
- **个人飞书只读同步**：默认每 10 分钟同步当天授权可见消息，跨会话搜索后批量取正文，保留话题、回复关系、消息 ID 和分页进度。机器人自身不能代替个人消息授权。
- **近五天展示、历史持续留存**：网页仅展示今天及前四天；更早的采集内容保存在 SQLite 和按日期生成的 Markdown 中。“与我相关”支持 @ 本人、本人消息、私聊和参与话题等筛选。
- **便于定制**：HTML/CSS/JavaScript + Python 标准库 + SQLite，没有前端编译步骤。可以直接修改布局、配色、提示词和数据处理逻辑。

![按学校分组的申请页，全部为虚构演示项目](docs/assets/applications.jpg)

## 适配范围

支持 Codex、可选飞书及可选申请快照。UI 保持中文，主要安装文档提供中英双语。补充原生 Windows 的 UTF-8、时区、SQLite 关闭和执行取消处理；Linux、Windows、macOS 运行自动检查，使用虚构数据及模拟账号，不等于替你完成真实账号授权。可选安装 Linux 登录自启服务：

```bash
python3 manage.py install-service
# 按输出执行 systemctl 命令。
```

默认只监听 `127.0.0.1`。这是本机应用，GitHub 用于分发代码，不会把后端变成 GitHub Pages 网站。电脑和后台服务需保持运行；不自动创建 Codex 桌面定时巡检。

## 数据说明

仓库不包含作者的私人飞书/Codex 账号配置、真实会话 ID、聊天记录、数据库、登录凭据或私人工作截图。`config.json` 只存非敏感配置，账号凭据由官方 CLI 管理；`data/`、`config.json`、`~/.codex` 和飞书凭据目录不要上传。

发布文件与公开署名的具体边界见 [发布隐私核对](docs/RELEASE-PRIVACY.md)。

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
