# 安装与恢复

本流程针对：AstrBot、QQ、模型已经能正常聊天；配置工具在 AstrBot 所在电脑上运行。第一阶段使用内置执行器 `local` 和 `/api/v1` 管理接口。未知接口或字段会停止，不猜测写入。

## A. 双击方式

1. 在目标 QQ 私聊中发 `/sid`，复制完整 UMO。
2. 解压整个包，双击 `导入鱼鱼.bat`。
3. 后台地址通常为 `http://127.0.0.1:6185`，以实际浏览器地址为准。填后台用户名、密码和 UMO；查看预览后输入“导入”。
4. 双击 `检查鱼鱼.bat`，填写与导入时相同的地址和 UMO。使用 `localhost` 导入后，检查也保持 `localhost`，不要来回替换为 `127.0.0.1`。
5. 按 `docs/Windows验收.md` 在 QQ 验证。此版本没有 `/鱼鱼状态` 或 `/鱼鱼表情` 命令。

BAT 通过一次性的 PowerShell 进程调用解释器；不会修改系统的长期脚本策略。系统策略阻止脚本时，可直接在终端运行 Python 命令。

找不到 Python 时，使用已有 AstrBot 解释器完整路径，或者设置 `YUYU_PYTHON` 后运行 BAT。Launcher 修改过实例根目录时，需要你指定正确的解释器；不要为解决本包问题重装现有 AstrBot。

```powershell
& 'C:\实际路径\python.exe' -X utf8 tools\manage.py install
```

## B. Agent / 回答文件方式

运行所用 Python 必须为 3.10 及以上。下面命令中的 `python` 可以替换为可用解释器的完整路径。

在包目录创建 `.local`，把 `examples/answers.example.json` 复制为 `.local/answers.json`。替换后台地址、用户名和 UMO。在 `.local/password.secret.txt` 里填写后台密码；文件与回答 JSON 同一目录。密码文件末尾换行会去掉，其他空格会保留。

回答文件是普通 JSON：

```json
{
  "base_url": "http://127.0.0.1:6185",
  "username": "astrbot",
  "password_file": "password.secret.txt",
  "origin": "实际平台ID:FriendMessage:实际会话ID"
}
```

凭证可改用 `password_env` 指定环境变量名，或用 `token_file` / `token_env` 提供 AstrBot API Key/后台令牌。文件路径相对于回答文件目录；不要把凭证正文填入 `password` 或 `token` 字段。API Key 需要所用接口的 `persona`、`config`、`data` 权限，`inspect` 还用到 `system`；复制包含管理员配置的源配置时，服务器也可能要求 `config:edit_admin`。有疑问优先使用本机后台登录。

按顺序执行：

```powershell
python -X utf8 tools/manage.py check
python -X utf8 tools/manage.py inspect --answers .local/answers.json --json
python -X utf8 tools/manage.py plan --answers .local/answers.json --json
python -X utf8 tools/manage.py install --answers .local/answers.json --yes --json
python -X utf8 tools/manage.py verify --answers .local/answers.json --json
```

`--answers` 自动采用非交互方式，缺信息直接报告，不挂着等输入。也可以逐项传入 `--base-url`、`--origin`、`--username`、`--password-file` 等参数，搭配 `--non-interactive`。没有命令行明文密码参数。

`inspect` 读取版本、配置文件 ID、当前会话绑定和相关服务状态，不输出完整后台配置。`plan` 预览，不写入后台。`install --yes` 执行已核对的范围。没有用户要求安装时，仅执行检查与预览。

默认继承当前会话实际匹配的配置。确有需要时，回答文件可加 `source_profile` 指定从哪个配置 ID 复制；它是内部 ID，不是显示名称。目标仍然是新建的专用配置。

成功会返回 `status=configured`，检查通过为 `ok=true`。所有自动结果仍显示 `qq_acceptance=pending`：工具没有代替你在 QQ 观察实际效果。重复安装同一版本会只读检查；如果你之后改过人格或节奏，停止覆盖并指出差异。

## C. 实际写入范围

1. 人格列表中没有同名人格就创建；同名且去掉首尾空白后内容相同则复用；内容不同停止。
2. 复制目标会话原配置，修改鱼鱼人格、按换行分段、长度等待、关闭流式/自动语音/文转图。源配置不变。
3. 精确绑定目标 UMO。AstrBot 的路由按第一条匹配生效，工具会把这个精确规则放在原有通配规则之前，并保持其他规则相对顺序。
4. 在目标会话的 `session_service_config` 里设置 `persona_id` 和 `tts_enabled=false`，保留其他字段。这个人格优先于历史对话自己选择的人格，不需要清空聊天记录或修改每条旧对话。
5. 保存有限恢复状态；不保存源配置全文、模型密钥、QQ 连接凭证、后台密码或令牌。

导入/恢复期间暂停同时编辑后台。AstrBot 没有提供原子条件更新，重新读取和冲突检查能降低覆盖风险，不能消除同时编辑的竞态。

## D. 恢复与失败处理

```powershell
python -X utf8 tools/manage.py restore --answers .local/answers.json --yes --json
```

或双击 `恢复鱼鱼设置.bat`。

恢复只还原本轮修改的会话字段、原配置绑定及其相对顺序，保留后来修改的其他字段。若同一项后来被修改，先报告冲突，不强行替换。恢复不删除人格和专用配置；它们保留在后台以便检查，确认无会话使用后可手动删除。

网络超时可能表示“后台已写入，但响应没收到”。安装状态会在每个写入前保存。不要删除 `.local` 后重新安装；先运行恢复。配置创建响应丢失时，恢复工具可按本轮唯一名称查找创建出的配置。

如果只存在 `.local/operation.lock`，确认之前的导入/恢复进程已经退出后，可以仅删除该锁文件；不要删除同目录的 JSON 状态。

从旧 v0.1.0 迁移：先在旧包运行它的恢复入口并检查结果；曾手动启用表情助手的，在后台停用旧助手。新包没有旧版表情插件，不自动操作来源不明确的旧安装。旧版若卡在先前的兼容问题，按旧包手动恢复说明处理；新版本使用不同人格 ID。

## E. 只用浏览器手动配置

1. 在 AstrBot 后台新增人格 `鱼鱼_温和搭子_v02`，系统提示词复制 `persona/鱼鱼.md` 正文；遇到不同内容的同名人格先保留旧版。
2. 复制目标 QQ 会话原先使用的配置，命名“鱼鱼第一阶段”，不要直接改全局默认配置。
3. 在复制的配置中选择鱼鱼人格、内置执行器，关闭流式回复、自动文字转语音和文字转图片。
4. 开启分段回复，设置“仅模型回复”、正则模式、按长度间隔 `log`、底数 `5.0`、长文本阈值 `150`，清空额外文本清理规则。正则复制 `[^\r\n]+(?:\r?\n|$)`。
5. 在会话/配置绑定页面，把目标完整 UMO 绑定到这份配置。如果已有通配绑定，确保精确绑定排在它前面。
6. 在会话自定义规则中，为这个 UMO 的“会话服务配置”选择鱼鱼人格；保留原有其他字段。若旧版没有该入口，则在后台切换当前对话人格，并记录这一步是手动完成的。
7. 按 Windows 验收表测试。手动恢复时切回原会话人格/规则与原配置绑定，再检查聊天正常；不要一律恢复成系统默认值。

没有对应字段、使用第三方执行器、已有插件接管回复时，记录实际 AstrBot 版本和错误，停止套用未知设置。
