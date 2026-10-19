# U8 单据打印与追溯记录

核对日期：2026-10-19。查询允许 `UFDATA_998_2021` 和 `UFDATA_008_2021`；008 正式账套只读，打印准备、补打和登记均阻止。新标签测试打印与追溯写入仅限 998，写入前还校验实际 `DB_NAME()`。本文描述当前格式，不包含真实业务数据。

## 已核对的历史格式

旧 .NET 打印平台按**每张标签**插入三条记录，而不是一张单据对应一组三表记录。当前网页版保留这一关联格式，并增加稳定明细身份：

| 表 | 主要内容 | 关联 |
| --- | --- | --- |
| `TraceBackOrder` | `orderType=打印平台`；JSON 为 `{"documentNumber":"单据号","orderType":"单据号中的字母"}` | `pdaOrderUuid` |
| `TraceBackGoods` | JSON 包含物料名称/编码、仓库/货位、批号、`warehouseCode`、`quantity: 0` | `pdaGoodsUuid` |
| `TraceBackOnlyCode` | `traceBackType=条码`、`sn`、`sum=本张标签数量`、登录用户、时间；条码为 `账套代码|存货编码|批号|数量|SN` | 同时保存两个 UUID |

历史数据还有 PDA 生成的扩展 Goods JSON，含库存、来源单据等较多字段。网页版按现有 .NET 打印平台的精简格式写入，并用 JSON 序列化器处理物料名称等特殊字符。

条码默认沿用 `008` 这个 PDA 账套段，这**不影响写入目标**。如需改变条码段，配置 `U8_BARCODE_ACCOUNT_CODE`；不得据此把追溯写入目标切换到 008。

## 操作和写入时机

1. 用户选单据、明细、数量、包装方式、模板、打印机，点击“打印”。未勾选任何明细时按当前单据全部明细处理；勾选后只处理勾选的明细。服务端重新读取 U8 单据和明细，检查物料/批号、数量范围后，为每张标签生成唯一 SN、条码和对应的三表数据。打印清单和留档 PDF 保存在本地持久目录。
2. 浏览器模式打开固定批次 PDF，由用户选择本机打印机并确认完成。助手模式将固定批次包发给访问电脑的 Windows 助手，使用本机驱动打印；Microsoft Print to PDF 逐张保存到客户端 `下载/标签打印`，文件名为 `单号_行号_SN.pdf`。当前流程不回退到服务器打印队列；旧服务端 `LABEL_PRINT_OUTPUT_DIR` 不控制客户端输出目录。
3. 用户确认或助手返回有效回执后，服务端核对批次所属用户、秘密回执、摘要、打印机和张数，先保存提交状态，再在 998 的一个 SQL 事务中写三表。插入失败全部回滚，原任务可重试登记而不重新打印；完整重复幂等，局部冲突拒绝继续。补打只保留生成记录，不执行首次追溯登记。

Windows 打印队列接收任务不能证明纸张已实际打印，实体打印机应检查队列和纸张状态。当前首页按明细及原始标签数量扣减进度，部分打印继续保留；旧记录无法唯一匹配时为待核对。OnlyCode 的 `sum` 可能已成为消费后的余额，不能用它直接计算首次打印进度。参考 [待打印 SQL](sql/pending-labels.sql)，最终唯一匹配和数量计算在 `u8_pending.py` 完成。

## 三表的具体写入值

每张标签各插入一条 `TraceBackOrder`、`TraceBackGoods`、`TraceBackOnlyCode`。同一明细拆成整包及尾数标签后，每张标签有独立的 22 位数字 `SN`；三个表用本张标签的 UUID 关联。数值以下面的示例说明，实际值取自单据明细：

| 表 | 写入列 | 写入值 |
| --- | --- | --- |
| `TraceBackOrder` | `json` | `{"documentNumber":"RK001","orderType":"RK","labelPrintSource":{"billType":"CGRK","billId":123,"detailId":"456","lineNumber":1}}`；数字为格式示例，`orderType` 从单号提取字母 |
|  | `pdaOrderUuid` | `SN` 加 `dyx`，例如 `2610021345001234567890dyx` |
|  | `orderType`、`time` | 固定 `打印平台`；本张标签的打印时间 |
| `TraceBackGoods` | `json` | `{"name":"物料名","code":"ITEM001","CurrencyGoodsData":{},"inventory":{"warehouse":"仓库名","storageLocation":"货位名","storageLocationCode":"P01"},"Attribute":{"batchNumber":"B01","productionDate":"9999-01-01","expirationDate":"9999-12-12"},"warehouseCode":"WH01","quantity":0.0}` |
|  | `pdaGoodsUuid`、`time` | `SN` 加 `syx`；同一本张标签的打印时间 |
| `TraceBackOnlyCode` | `traceBackCode` | `008|ITEM001|B01|50.00|2610021345001234567890`，依次为条码账套段、物料编码、批号、本张标签数量、SN |
|  | `traceBackType`、`pdaOrderUuid`、`pdaGoodsUuid` | 固定 `条码`；分别引用上面两条记录的 UUID |
|  | `sn`、`sum`、`User`、`time` | 本张标签 SN、本张标签数量（两位小数）、当前登录账号、打印时间 |

`008` 是条码中的 PDA 账套段，**不是**写入的数据库名。SQL 连接在写入前会检查 `DB_NAME()` 必须为 `ufdata_998_2021`。三条记录作为同一事务写入；只要其中一条失败就全部回滚。

库存 Order JSON 使用 `{"documentNumber":"YYYYMMDDHH","orderType":"KC"}`，实际 documentNumber 为打印时刻的日期小时，批号仍取库存 `cBatch`。补打次数等待供应商确认，当前不写额外计数。新增 `labelPrintSource` 不改变三表结构，也不回填历史记录。
