# GitHub 发布顺序

建议：先完成 Windows 实机验收，再正式发布。把代码放上 GitHub 与对外承诺“可以直接使用”是两件事；需要验证链接安装流程时，可先发布明确标记为候选版的版本。

## 1. 验收候选包

把 `鱼鱼人格配置包-v0.2.0-rc.1.zip` 传到 Windows，解压后按 `Windows验收.md` 检查。保留原 ZIP，不要再压缩运行过的目录分享。遇到问题先修复，再重新构建和复验相关步骤。

## 2. 整理仓库

只上传 `yuyu-persona-pack` 目录作为仓库根目录，不要上传外层工作目录、审计文件夹、AstrBot 对照源码或原始旧包。首页应直接看到 README.md、INSTALL.md、AGENTS.md、persona/、settings/、tools/、tests/。

仓库名可用 `yuyu-persona-pack`。上传前确认暂存文件没有 `.local`、密码文件、回答文件或运行日志。`.gitignore` 是辅助，发布文件仍需核对；本包构建器另有明确文件清单。

## 3. 构建并检查

```text
python -m unittest discover -s tests -v
python tools/build_pack.py
python tools/manage.py check
```

构建输出在源文件夹的上一级，包含完整 ZIP 和外层 SHA-256 文件。包内 `SHA256SUMS.json` 覆盖源码、人格、配置、文档和测试，不包含个人安装状态。

如需在 GitHub 下载源码 ZIP 后直接安装，应提交更新后的 SHA256SUMS.json。`.gitattributes` 固定源文件换行，BAT 保持自己的 CRLF；不要在上传时手工转换编码。

## 4. 先候选，后正式

实机未通过时保留 `0.2.0-rc.1`，如发布 Release，勾选预发布并写清哪些项目未验收。GitHub 自动检查运行后，阅读实际结果；检查未运行不等于通过。

实机通过后，补充实际测试环境、日期和结果摘要。把清单及相关文档中的版本同步到正式版本（例如 `0.2.0`），更新 CHANGELOG，重新跑检查和构建，再发布对应版本与附件。

## 5. 让使用者把链接交给 Agent

教程的前一部分负责 AstrBot、QQ、模型连接。后一部分给出仓库链接，以及 README 中那段安装指令。使用者还需提供自己目标会话的 UMO，并在本机完成后台认证。

先让一名使用者从干净下载目录跑通“打开 GitHub 链接 → Agent 阅读说明 → 预览 → 配置 → QQ 验收”，确认没有依赖制作者电脑上的私有路径或旧状态，再扩大分发。

后续语音、表情、长期记忆按独立阶段增加，各自有开关、前提、验收和恢复说明，不在第一阶段默认安装。
