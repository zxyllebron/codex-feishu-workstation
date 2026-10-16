# 配置自己的飞书账号与消息同步

[English](FEISHU.md) · [官方 CLI](https://github.com/larksuite/cli)

## 账号和机器人是什么关系

需要你自己的飞书账号，以及租户允许进行**用户授权**的应用。机器人加入群聊，并不代表能读取你全部私人沟通。本项目默认用用户身份读取，私人提醒才使用应用的机器人身份。无需回响，也不会借用别人的应用、token 或桥接配置。

应用无法绕过企业管理员审批、可见范围、消息保留规则或权限限制。如果所在租户无法开通下面的消息权限，就需要管理员提供合规可用的接入方式；不能用机器人 token 冒充个人全量访问。

## 1. 安装 CLI

```bash
npx @larksuite/cli@latest install
lark-cli --version
python3 manage.py init
```

实现核对使用飞书 CLI **1.0.88**。后续版本的流程或输出可能变化，可结合 `--help` 排查。[官方安装和认证说明](https://github.com/larksuite/cli#installation--quick-start)。

## 2. 新建应用或使用已有应用

```bash
python3 manage.py feishu-setup
```

该命令在独立配置环境中运行官方 `config init`。按提示新建应用，或填写你已有应用的 App ID / App Secret；在浏览器中完成创建、可用范围或管理员审批。如果明确需要新应用，可运行：

```bash
python3 manage.py feishu config init --new
```

企业自建应用也可从 [飞书开发者后台](https://open.feishu.cn/app) 创建或选择。将可用范围设为包含自己，在权限管理中开启下面的**用户身份权限**，按企业流程发布或申请生效，再通过同一个配置助手接入。创建应用与个人同意授权是两个步骤。

如果使用非交互 App ID 方式，可查看 `python3 manage.py feishu config init --help`，用 `--app-secret-stdin` 从标准输入提供密钥，避免密钥出现在进程参数。不要把 App Secret 写入 `config.json`、命令历史、教程或 GitHub。

默认凭据目录是 `<data_dir>/feishu-cli`。设置了 `feishu_cli_dir` 就使用对应专用目录。官方 CLI 负责本地凭据和适用的系统钥匙串；工作台不在网页中展示 token。**所有安装、登录、查询都使用 `manage.py feishu*`**，避免直接运行 `lark-cli` 登录到了另一个配置目录。不要复制回响或他人的凭据。

## 3. 开启并授予只读用户权限

| 权限 | 用途 |
|---|---|
| `offline_access` | 在平台支持时持续刷新授权 |
| `search:message` | 跨会话搜索消息 |
| `im:chat:readonly` | 读取会话元信息 |
| `im:message:readonly` | 读取消息正文 |
| `im:message.group_msg:get_as_user` | 以本人身份读取授权群消息 |
| `im:message.p2p_msg:get_as_user` | 以本人身份读取授权私聊 |

```bash
python3 manage.py feishu-login
python3 manage.py feishu-status
python3 manage.py feishu auth check --scope "search:message im:chat:readonly im:message:readonly im:message.group_msg:get_as_user im:message.p2p_msg:get_as_user" --json
```

登录助手只请求这六项，不请求整个功能域的全部权限。在浏览器授权页核对并自行确认，不勾选无关权限；企业审批仍可能必需。网页“连接个人飞书”按钮用于应用配置完成后的用户授权，不负责安装 CLI 或填写应用密钥。

助手配置/登录成功后，重启已经运行的工作台，清除旧连接缓存。进入“记忆与消息 → 飞书消息”检查连接并开始采集。`ready=true、mode=user、phase=ready` 表示授权检查通过；还需采集任务完成、错误和待处理项为空，才能说选定范围遍历完成。

## 4. 读取原理和覆盖边界

个人适配器只放行四个读取用途接口：

```text
POST /open-apis/im/v1/messages/search
GET  /open-apis/im/v1/messages/mget
POST /open-apis/im/v1/chats/batch_query
GET  /open-apis/authen/v1/user_info
```

先按时间范围跨会话检索并分页，再每批最多 50 条取完整正文、核对消息 ID，补充会话名，保留发送者、时间、话题和回复关系。正文确认齐全后才推进游标，缺页或游标循环不会假报完成。旧话题里的新回复可由时间搜索找到，无需逐群展开。参考 [官方搜索实现](https://github.com/larksuite/cli/blob/main/shortcuts/im/im_messages_search.go)。

普通消息、富文本和卡片文字会归一化；图片、音视频、文件只保留元信息或占位，不下载或声称理解其正文。撤回消息、平台索引/保留限制、合并转发和权限限制可能留下缺口。“全部可见历史”只代表 API 在授权范围内可返回的记录，不是无限制账号备份。

后台默认每 10 分钟刷新**当天**。要补以前的消息，在网页选择较大范围后手动开始；无论采集范围多大，网页列表仍只显示近五天，历史保存在 Markdown 和 SQLite。暂停后自动同步尊重暂停状态；续传沿用原截止时间和游标，要覆盖截止时间后的新消息需启动新一轮。

## 5. 可选：只发给自己的提醒

保持“飞书提醒”关闭，即可只使用只读采集。若需要提醒，应用须开启机器人能力和**应用身份权限** `im:message:send_as_bot`，将本人加入可用范围，按要求发布/审批；部分租户需先在飞书中打开机器人的个人会话。

在网页设置中启用提醒，再主动点击测试。后台重新读取当前授权用户身份，只向这个用户的 `open_id` 发送，不接受群 ID 或任意其他收件人。发送失败显示在通知中心，不改变采集成功状态。这项写权限仅用于可选提醒，不属于上面六项用户登录权限，纯采集不需要。

## 6. 撤销和切换账号

```bash
python3 manage.py feishu auth logout
```

也可在飞书授权应用管理中撤销。换应用或账号时重新运行配置和登录助手；助手成功后清理缓存的身份和会话名，再重启工作台。历史采集内容不会因退出账号自行删除，因此不同用户应使用不同的数据目录、凭据目录和个人实例。

## 故障排查

- 找不到 CLI：填写 `lark_bin` 绝对路径后重启。
- 终端已登录、网页没登录：核对是否都使用助手的独立配置目录、同一系统用户、相同 `WORKSTATION_CONFIG` 和钥匙串会话。
- 缺权限/拒绝访问：同时检查应用已开权限、个人实际同意权限及企业审批，再重新授权。
- 授权过期/被撤销：重新登录，不要靠反复采集掩盖授权失败。
- `partial/error`：查看具体错误并续传，不当作全量完成。
- 没有新消息：核对范围、截止时间、暂停状态、消息可见性和索引延迟。
- 提醒失败：检查机器人应用身份发信权限和本人可用范围；采集可独立正常。
- 浏览器备用通路：见 [FEISHU_BROWSER.md](../FEISHU_BROWSER.md)。需要外部、已有授权的浏览器工作者；本项目不内置自动浏览器，不绕过企业权限。
