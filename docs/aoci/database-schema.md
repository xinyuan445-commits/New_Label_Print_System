# 数据结构与关联（不含业务数据）

依据 `backend/app/models`、Alembic 迁移、U8 SQL 和 `bill_printing.py` 整理。本文不代表对真实数据库进行过结构探测。AOCI 当前原生数据库支持不包含本项目使用的 SQL Server / SQLite，因此暂不生成数据库 Volume。

## 应用数据库

| 模型/表 | 作用与关联 |
| --- | --- |
| User / users | 唯一登录标识 email（允许非邮箱账号）、散列密码、角色、语言、启用状态、创建/修改时间、last_login_at |
| UserDisabledPage / user_disabled_pages | user_id + page 复合主键；按账号禁用功能，User.permissions 计算最终权限，管理员有特殊权限规则 |
| UserHiddenPage / user_hidden_pages | user_id + page 复合主键；按账号隐藏菜单，User.visibility 与权限分开计算 |
| BillFavorite / bill_favorites | user_id、bill_type、position；账号与类型唯一，顺序持久保存，接口限制最多 8 项 |
| Template / templates | 画布 JSON、标签规格、创建者、目录、共享属性与时间；访问由 shared_templates_enabled 控制 |
| TemplateVersion / template_versions | 模板版本快照与模板关联，用于历史查看和恢复 |
| LabelFormat / label_formats | 纸张毫米尺寸和规格类型，本地入口补齐缺失系统规格 |
| Asset / assets | 图片资产元信息；实际字节在 assets 目录 |
| Dataset / datasets | 数据集列结构与数据源配置；文件在 uploads 目录 |
| Folder / folders | 模板/数据集目录、颜色及封面等导航信息 |
| Device / devices、PrintJob / print_jobs | 连接器设备与任务，区别于浏览器本机默认打印机设置 |
| GeneratedFile / generated_files | 文件所属用户、来源模板、模板名快照、类型、模式、文件名、行数与生成时间；模板删除后保留记录，文件在 pdfs 目录 |
| Capture / captures | 打印捕获文件及设备相关信息 |

SQLite 本地文件为 `.local-data/pilot.db`，不是 U8 的业务数据库。备份需覆盖整个 `.local-data` 并考虑写入一致性，单独导出模板不足以恢复所有用户配置。

## U8 查询依赖

- `services/u8_sql` 的 main/detail 成对 SQL 对应单据类型，输出中文业务字段，参数由 `u8_bills.bind_query` 转为 pyodbc 参数，不能把用户输入拼入 SQL。
- `CurrentStock` / `InvPositionSum` 与 Inventory、Warehouse、ComputationUnit、Position 关联得到库存；Position 关联包括仓库编码，避免跨仓货位重名。
- `CheckVouch` / `CheckVouchs` 提供盘点单与实盘数量。

## 追溯三表

初次打印按每张标签各写入三条记录，拆包后的不同标签有独立 SN。以下是格式说明，不含真实单据样本。

| 表 | 列与值 |
| --- | --- |
| TraceBackOrder | `[json]` 为 documentNumber + orderType；pdaOrderUuid 为 SN 加 `dyx`；外层 orderType 固定 `打印平台`；time 为打印时间 |
| TraceBackGoods | `[json]` 含 name、code、CurrencyGoodsData、inventory、Attribute、warehouseCode、quantity；pdaGoodsUuid 为 SN 加 `syx`；time 同标签时间 |
| TraceBackOnlyCode | traceBackCode=`账套段\|料号\|批号\|数量\|SN`；traceBackType=`条码`；同时保存两个 UUID；sn、sum、User、time 对应标签与当前登录账号 |

Goods 的 inventory 包含 warehouse、storageLocation、storageLocationCode；Attribute 包含 batchNumber、productionDate=`9999-01-01`、expirationDate=`9999-12-12`；quantity 按既有格式为 0。单据 Order JSON 的 orderType 从单据号提取字母，库存打印为 `KC`。标签数量在条码和 OnlyCode.sum 中表达，不能拿 Goods.quantity 计算标签剩余量。

`confirm_run` 对实际数据库、运行清单所属用户、UUID/条码已存在数量进行校验，在同一个数据库事务中写三表；失败回滚。登记重试使用同一清单身份，不重复生成 SN；部分三表已存在属于需处理的不一致状态。

新单据记录在 Order JSON 中增加 `labelPrintSource`，保存 `billType`、`billId`、`detailId` 和 `lineNumber`。旧键及库存 KC 格式保留，不修改三表结构，不回填历史数据。明细查询额外输出单据 ID 和 AutoID；标签中的行号仍按原明细顺序。历史记录只有在单据与完整物料身份唯一匹配时计入，缺失或矛盾记录保留待核对。待打印扣减使用原条码数量，OnlyCode.sum 可能代表后续余额，不能直接相加作首次打印数量。

PDA 移动及补打通过两个 UUID 关联三表，剩余标签量由 OnlyCode 的带符号数量事件计算。仅按 SN 计数无法得出剩余库存，也不能代替待打印判定。
