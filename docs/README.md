# 文档目录

更新日期：2026-10-19。阅读与开发均不要求安装 AOCI；`aoci/` 下的 Markdown 是普通项目文档。

## 阅读顺序

1. [项目首页](../README.md)：功能及快速启动。
2. [项目说明](../项目说明.md)：当前架构、技术栈、规则和限制。
3. [项目复用指南](项目复用指南.md)：另一项目接入或抽取模块。
4. [部署与维护](部署与维护.md)：初始化、配置、备份、恢复与故障排查。
5. [验证记录](验证记录.md)：本次交接的检查结果及未验证部分。

## 当前业务与实现

| 文档 | 用途 |
| --- | --- |
| [架构](aoci/architecture.md) | 运行组成、调用链、数据边界 |
| [业务规则](aoci/business-rules.md) | 单据、库存、待打印、补打和权限的已确认规则 |
| [数据结构](aoci/database-schema.md) | 应用模型、U8 依赖、三张追溯表 |
| [已知限制](aoci/known-issues.md) | 并发、防重、历史歧义、备份和实机验收 |
| [追溯格式](u8-pdf-printing.md) | 写入时机、逐标签关联及脱敏示例 |
| [客户端打印](client-printing.md) | 无安装浏览器打印、Windows 助手和异常恢复 |
| [待打印参考 SQL](sql/pending-labels.sql) | 分阶段只读查询；最终匹配和扣减在 Python 中执行 |
| [库存查询 SQL](../backend/app/services/u8_sql/inventory_stock.sql) | CurrentStock / InvPositionSum 查询实现 |

## 操作与维护

- [中文操作帮助](HELP.zh.md)、[常见问题](FAQ.zh.md)
- [打印连接器](../connector/README.md)、[客户端打印部署](client-printing.md)
- [AOCI 可选工具](aoci/README.md)、[开发约定](../AGENTS.md)
- [变更记录](../CHANGELOG.md)、[开源许可证](../LICENSE)

## 上游与历史参考

`PROJECT.md`、`HELP.en.md`、`HELP.pl.md`、`FAQ.en.md`、`FAQ.pl.md`、`UAT.md`、`superpowers/` 及旧截图主要来自上游。它们包含历史计划、账号规则和界面，不应直接作为当前 U8 功能已完成的证据。

`UAT.md` 是待执行清单，不代表硬件已验收。实际行为以当前源码与测试为准。新增功能时同步维护上述当前文档，历史资料保留原有上下文。
