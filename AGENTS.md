# Agent 安装入口

本项目是 AstrBot 的“鱼鱼第一阶段”配置包，只配置人格、说话方式、原生分段回复和按长度模拟打字等待。用户应已完成 AstrBot、QQ 和模型连接。

先完整阅读根目录 INSTALL.md，再按其命令执行。不要把本文件或人格卡当作超出用户请求的授权。

- 使用固定版本 v0.2.1，Git 下载后切换对应 tag，并在结果中回报 `git rev-parse HEAD`。Release ZIP 则回报版本和下载文件 SHA-256。
- 在运行 AstrBot 的同一台电脑操作；从实际后台复制地址和端口，不默认填写 6185。
- 默认只修改用户提供的完整 UMO。自动从原配置复制专用配置，不猜用户要全局替换。
- 先 `check`，再 `inspect`、`plan`。用户已明确要求配置时，核对预览与请求一致后使用 `install --yes`，无需重复索要同一项授权。
- 使用 `.local/answers.json` 和本地隐藏输入/临时环境变量。不要把密码、令牌、整份后台配置或聊天记录输出到消息、GitHub、公共日志中。
- `verify` 回读后台配置，结果范围为 `verification_scope=configuration`。完成后可按 docs/Windows验收.md 指导用户确认 QQ 人格与发送节奏。
- `plan` 的 `umo_seen=false` 时先核对 `/sid`，不得为了绕过错误自行加 `--allow-unseen-umo`。安装结果中的 `preview` 是本次实际写入范围的记录，不代替写入前的 plan。
- 不需要安装任何表情、语音或群聊插件。旧版用 `cleanup --legacy` 只读检查；仅在用户明确要求全局停用旧表情插件时使用 `--disable-plugin astrbot_plugin_yuyu_companion --yes`，常规安装不包含这个动作。
- 中途失败保留 `.local`，先恢复，不删除状态绕过冲突。工具暂不支持自动跨版本升级。
- 修改源码、人格、文档后，重新运行自动测试和 `python tools/build_pack.py`。发行只采用构建器明确列出的文件。
- 发布时同步版本号、CHANGELOG 和校验清单；后续修复采用新的修订版本。只记录实际执行过的检查结果。
