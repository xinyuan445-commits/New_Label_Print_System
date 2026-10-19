# AOCI 使用说明

本项目使用 AOCI-CODE `0.1.0-rc17`，工具放在 `tools/aoci/aoci.exe`。仅管理 BarcodeLabelGen，不创建嵌套 Git 仓库，不改动上层项目。

独立发布仓库是 `xinyuan445-commits/New_Label_Print_System`，项目内容直接位于仓库根。工具的 `--repo` 应指向实际克隆根目录，不照搬原机器的 `labelPrint/BarcodeLabelGen` 绝对路径。

## 无 AOCI 的项目或电脑

AOCI 不参与应用运行。没有工具时，从项目根 `README.md`、`项目说明.md` 和 `docs/README.md` 开始，继续读取源码、测试及业务文档；这里的 architecture / business-rules / database-schema / known-issues 都是可直接阅读的普通 Markdown。

本次若没有校验工具，应注明索引未校验，不手改 aoci*.txt，不伪造同步结果。完整副本换路径后须按实时 Guide 核对路径、基线和正式索引；抽取部分模块到新项目时重新建立目标项目认知，不把本项目的索引当作目标索引。具体见 `docs/项目复用指南.md`。

## Git 同步范围

上传 `aoci.txt`、`aoci.meta.txt`、`aoci.code.txt`、`.aoci/.gitignore`、`.aoci/config.json`、`.aoci/baseline.json`，以及实际存在且被白名单允许的正式策展/数据库基线文件。工具本体、下载包、诊断输出、ledger、drafts、transactions、verify_history 和本机配置不上传。

索引中现有目录标记可能含原工作区绝对路径。它是当前仓库的认知资产，不是跨机器安装配置；换路径不要手工替换索引或强制覆盖基线，应使用相同版本工具按 Guide 处理。Git 上传源码不等于迁移 SQLite、用户模板、U8 业务数据或客户端账本。

## 在 Codex 中使用

1. 将 `BarcodeLabelGen` 目录作为 Codex 项目打开；本目录的 `.codex/config.toml` 配置了 `aoci` MCP。当前若从上层 labelPrint 打开，不能假设会加载子目录配置。
2. 在 MCP 设置中确认 `aoci` 连接成功。配置刚写入时，支持动态重载的宿主可以重启 MCP；仍未出现工具时重新打开本项目会话。无需删除原对话，也无需重启标签网页服务。
3. 项目运行约定在 `AGENTS.md`。Agent 使用实时 Rules / Overview / Guide 和维护工具，完成修改后同步维护索引。

MCP 固定调用项目内二进制，并通过 `--repo` 指定 BarcodeLabelGen 的绝对路径。`aoci.exe mcp` 使用 stdio，由 Codex 按需启动，不要单独双击启动。没有额外 AOCI API Key；本地工具未配置 AI endpoint。

## 日常检查

从本目录执行：

```powershell
.\tools\aoci\maintenance.ps1 verify
.\tools\aoci\maintenance.ps1 check
.\tools\aoci\maintenance.ps1 doctor
.\tools\aoci\maintenance.ps1 guide
```

脚本从自身位置确定项目目录，因此从其他工作目录调用也不会把上层项目纳入扫描。`scan` 用于实时 Guide 要求的基线操作，不能用强制扫描绕过已有变化或恢复状态。

## 内容与排除

- 正式入口：`aoci.txt`、`aoci.meta.txt`、`aoci.code.txt`；治理配置在 `.aoci`。正式认知和允许版本化的配置随源码保留。
- 项目说明：architecture / business-rules / database-schema / known-issues。上游历史设计与截图属于 observe 参考资料，不能当作当前业务事实。
- 排除：`.env`、`.local-data`、数据库文件、PDF、日志、依赖与构建目录、工具下载及运行诊断。现有两个 `tsbuildinfo` 文件仅记录为编译缓存元数据。`.codex/config.toml` 含本机路径，不提交。
- SQL Server / SQLite 第一版只按源码和脱敏表结构文档记录，不启用 Database Volume。

`tools/aoci/mcp_client.py` 是安装诊断的 JSON-RPC 传输工具，使用项目 Python 虚拟环境即可运行；它不替代 Codex 的工具加载和完整认知验证，不硬编码 AOCI 创作状态机。诊断结果保存在被排除的 `tools/aoci/runtime`。

## 工具恢复与升级

二进制和下载目录不提交。换电脑时，从官方 Release 下载同版本 Windows 对应架构压缩包与 SHA256SUMS，核对包 SHA-256 后解压，将 aoci.exe 放回 tools/aoci；保留发布包中的许可和 NOTICE。然后使用显式 `--repo` 的 init --agent codex 重建本机配置；已有配置需要核对绝对路径，不能直接复制另一台电脑的路径。

安装校验记录在 `tools/aoci/runtime/installation.json`。当前只完成压缩包校验和二进制身份验证，没有声称完成 Cosign 发布者签名或完整构建溯源验证。

升级前保留旧工具及正式索引，核对官方迁移说明。AOCI 处于发布候选阶段，不能直接用新版本覆盖后强制扫描。

参考：

- https://github.com/aoci-spec/aoci-code/blob/v0.1.0-rc17/docs/install.md
- https://github.com/aoci-spec/aoci-code/blob/v0.1.0-rc17/docs/agent-integrations.md
- https://developers.openai.com/codex/mcp
