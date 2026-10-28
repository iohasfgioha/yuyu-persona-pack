# 安装与恢复

本流程针对：AstrBot、QQ、模型已经能正常聊天；配置工具在 AstrBot 所在电脑上运行。第一阶段使用内置执行器 `local` 和 `/api/v1` 管理接口。未知接口或字段会停止，不猜测写入。

## A. 双击方式

1. 打开正在使用的 AstrBot 后台，从浏览器地址栏复制实际地址和端口，只保留协议、主机、端口，去掉页面路径或 `/#/...`。Launcher 用户从实例的“打开后台”入口进入；不要照抄 6185，也不要从 `cmd_config.json` 推测运行端口。若找不到入口，先在 Launcher 实例页面查看后台地址。
2. 在目标 QQ 私聊中先聊一句，再发 `/sid`，复制完整 UMO。
3. 解压整个包，双击 `导入鱼鱼.bat`（或英文入口 `install.bat`）。填写上述实际地址、后台用户名、密码和 UMO；查看预览后输入“导入”。后台地址没有默认值。
4. 双击 `检查鱼鱼.bat`（或 `verify.bat`），填写与导入时相同的地址和 UMO。使用 `localhost` 导入后，检查也保持 `localhost`，不要来回替换为 `127.0.0.1`。
5. 按 `docs/Windows验收.md` 在 QQ 确认聊天效果。此版本没有 `/鱼鱼状态` 或 `/鱼鱼表情` 命令。

找不到后台时先确认实例已经启动。无法连接和写入后超时的提示不同：只有写入请求超时才需要考虑后台已经写入、但响应未收到的情况。不通过向多个本机端口尝试登录来猜后台。

BAT 通过一次性的 PowerShell 进程调用解释器；不会修改系统的长期脚本策略。系统策略阻止脚本时，可直接在终端运行 Python 命令。

找不到 Python 时，使用已有 AstrBot 解释器完整路径，或者设置 `YUYU_PYTHON` 后运行 BAT。Launcher 修改过实例根目录时，需要你指定正确的解释器；不要为解决本包问题重装现有 AstrBot。

```powershell
& 'C:\实际路径\python.exe' -X utf8 tools\manage.py install
```

## B. Agent / 回答文件方式

运行所用 Python 必须为 3.10 及以上。下面命令中的 `python` 可以替换为可用解释器的完整路径。

先获取固定版本并记下提交号：

```powershell
git clone --branch v0.2.1 --depth 1 https://github.com/iohasfgioha/yuyu-persona-pack.git
cd yuyu-persona-pack
git rev-parse HEAD
```

没有 Git 时下载 v0.2.1 Release ZIP，记录 ZIP 的 SHA-256。包内校验用于检测文件变化，不是作者身份签名；不要将它当作任意未来 main 代码的执行授权。

在包目录创建 `.local`，把 `examples/answers.example.json` 复制为 `.local/answers.json`。填写实际后台地址、用户名和 UMO。默认采用临时进程环境变量，不把密码存进包目录、OneDrive、Documents 或聊天记录。

回答文件示例（地址字段必须替换）：

```json
{
  "base_url": "请替换为浏览器中的本机后台地址和实际端口",
  "username": "astrbot",
  "password_env": "YUYU_DASHBOARD_PASSWORD",
  "origin": "实际平台ID:FriendMessage:实际会话ID"
}
```

在本机 PowerShell 安全输入凭证，然后在同一终端运行后面的命令：

```powershell
$yuyuCredential = Get-Credential -UserName astrbot -Message '请输入 AstrBot 后台密码'
$env:YUYU_DASHBOARD_PASSWORD = $yuyuCredential.GetNetworkCredential().Password
```

操作结束后清除临时变量：

```powershell
Remove-Item Env:YUYU_DASHBOARD_PASSWORD -ErrorAction SilentlyContinue
Remove-Variable yuyuCredential -ErrorAction SilentlyContinue
```

也可直接运行不带 `--answers` 的交互入口，密码隐藏输入。若必须用文件，将凭证放到 `%LOCALAPPDATA%\YuyuPack\` 下，并使用展开后的绝对路径填写 `password_file`；不要放进同步目录。`chmod(0600)` 在 Windows 上不提供用户 ACL 隔离，凭证所在文件夹的访问权限需要由本机用户管理。

凭证还可用 `token_env` 或 `token_file` 提供 AstrBot API Key/后台令牌。文件路径相对于回答文件目录；不自动展开 `%变量名%`，密码文件只去掉末尾换行。不要把正文填入 `password` 或 `token` 字段。API Key 需 `persona`、`config`、`data` 权限，`inspect` 还用到 `system`，`cleanup --legacy` 用到 `plugin`；复制包含管理员配置的源配置时也可能需要 `config:edit_admin`。有疑问优先本机后台登录。

按顺序执行：

```powershell
python -X utf8 tools/manage.py check
python -X utf8 tools/manage.py inspect --answers .local/answers.json --json
python -X utf8 tools/manage.py plan --answers .local/answers.json --json
python -X utf8 tools/manage.py install --answers .local/answers.json --yes --json
python -X utf8 tools/manage.py verify --answers .local/answers.json --json
```

`--answers` 自动采用非交互方式，缺信息直接报告，不挂着等输入。也可以逐项传入 `--base-url`、`--origin`、`--username`、`--password-file` 等参数，搭配 `--non-interactive`。没有命令行明文密码参数。

`inspect` 读取版本、配置文件 ID、当前会话绑定和相关服务状态，不输出完整后台配置。`plan` 预览，不写入后台，也不占用导入/恢复的写入锁。`install --yes` 执行已核对的范围，并在 JSON 的 `preview` 中保留本次改动清单；重复安装也返回清单。写入前的 `plan` 仍应先执行。没有用户要求安装时，仅执行检查与预览。

`inspect` 和 `plan` 会返回 `umo_seen`。为 false 时，先在目标 QQ 会话发普通消息，再重新复制 `/sid`；安装默认停止，不创建路由。只有用户明确确认要配置尚无聊天记录的新会话时，才给 install 加 `--allow-unseen-umo`，不能将它当作通用报错修复参数。

默认继承当前会话实际匹配的配置。确有需要时，回答文件可加 `source_profile` 指定从哪个配置 ID 复制；它是内部 ID，不是显示名称。目标仍然是新建的专用配置。它是导入时的副本，之后修改 default 不会自动同步到鱼鱼会话；请编辑鱼鱼专用配置。

成功会返回 `status=configured`，检查通过为 `ok=true`。`verification_scope=configuration` 表示回读检查覆盖后台配置；聊天效果可按安装后检查说明确认。重复安装同一版本会只读检查；如果你之后改过人格或节奏，停止覆盖并指出差异。

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

从 v0.1 或 v0.2.0 更新，请按 [旧版迁移](docs/旧版迁移.md) 操作。不要通过删除 `.local` 绕过版本检查。

## E. 只用浏览器手动配置

1. 在 AstrBot 后台新增人格 `鱼鱼_温和搭子_v021`，系统提示词复制 `persona/yuyu.md` 正文；遇到不同内容的同名人格先保留旧版。
2. 复制目标 QQ 会话原先使用的配置，命名“鱼鱼第一阶段”，不要直接改全局默认配置。
3. 在复制的配置中选择鱼鱼人格、内置执行器，关闭流式回复、自动文字转语音和文字转图片。
4. 开启分段回复，设置“仅模型回复”、正则模式、按长度间隔 `log`、底数 `5.0`、长文本阈值 `150`，清空额外文本清理规则。正则复制 `[^\r\n]+(?:\r?\n|$)`。
5. 在会话/配置绑定页面，把目标完整 UMO 绑定到这份配置。如果已有通配绑定，确保精确绑定排在它前面。
6. 在会话自定义规则中，为这个 UMO 的“会话服务配置”选择鱼鱼人格；保留原有其他字段。若旧版没有该入口，则在后台切换当前对话人格，并记录这一步是手动完成的。
7. 按安装后检查说明确认聊天效果。手动恢复时切回原会话人格/规则与原配置绑定，再检查聊天正常；不要一律恢复成系统默认值。

没有对应字段、使用第三方执行器、已有插件接管回复时，记录实际 AstrBot 版本和错误，停止套用未知设置。

## F. 文件校验与本地修改

`tools/manage.py`、`tools/run.ps1`、三个英文 BAT、`settings/pack.json`、`persona/yuyu.md` 是运行核心，缺失或变化会停止导入及恢复。README、INSTALL、AGENTS、其他说明、中文别名、测试和 CI 等辅助文件变化只进入 JSON 的 `warnings`，不会因为写备注或翻译说明而阻断安装。

`persona/yuyu.md` 是人格真源，`persona/鱼鱼.md` 是构建时生成的中文阅读副本。需要修改人格时编辑真源，运行 `python tools/build_pack.py` 更新副本和清单。核心文件缺失时先重新完整解压；中文文件名乱码时可用英文 BAT 和 ASCII 人格文件。
