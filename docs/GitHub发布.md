# GitHub 发布与版本维护

当前版本为 **v0.2.1**。仓库链接固定，后续修复通过新的修订版本发布，例如 v0.2.2；新增章节时再更新相应版本。

## 1. 整理仓库

只上传 `yuyu-persona-pack` 目录作为仓库根目录，不上传外层工作目录、审计资料、AstrBot 对照源码或原始旧包。首页应直接看到 README.md、INSTALL.md、AGENTS.md、persona/、settings/、tools/、tests/。

发行包只采用构建器列出的文件，不包含 `.local`、密码文件、个人回答文件和运行日志。

## 2. 构建发行包

同步 `settings/pack.json`、README、CHANGELOG 和文档中的版本号，然后运行：

```text
python tools/build_pack.py
```

构建器更新 `SHA256SUMS.json`，并在源码文件夹上一级输出 `yuyu-persona-pack-v0.2.1.zip` 和对应 SHA-256 文件。`.gitattributes` 固定源文件换行，BAT 保持 CRLF。不要手工转换编码，也不要重新压缩使用过的目录。

## 3. 发布 Release

提交源码与更新后的校验清单，创建对应版本标签和 Release，附上构建得到的 ZIP 与校验文件。版本说明列出功能与使用方式，后续修复记录在 CHANGELOG。GitHub 自动检查结果可在 Actions 页面查看。

## 4. 把链接交给 Agent

教程前半部分完成 AstrBot、QQ 和模型连接。后半部分提供固定版本标签链接与 README 中的安装指令。Agent 需要在 AstrBot 所在电脑执行操作；使用者提供目标会话的 UMO，并在本机完成后台认证。

安装后可按 `Windows验收.md` 确认人格、分段回复与打字等待，使用 `验收记录模板.md` 记录环境和问题。

后续语音、表情、长期记忆按独立章节增加，各自提供开关、前提、使用检查和恢复说明。
