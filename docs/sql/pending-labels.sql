-- 待打印标签查询：只读，不修改 U8 数据及三表结构。
-- 在 SSMS 中手动选择要检查的账套。008 仅查询，测试写入只允许 998。
-- 应用使用参数绑定；这里的 DECLARE 仅便于人工核对。
-- 查询分为候选单据、明细、追溯数据；最终匹配与数量扣减在 u8_pending.py 中完成。
-- 不能用“单号存在打印平台记录”排除整单，也不能直接 SUM(OnlyCode.sum)。
-- 单据类型/ID + 明细 ID + 料号 + 批号 + 仓库 + 货位确定匹配；SN 去重。
-- 所需数量 - 原条码中的已打印数量 = 待打印数量；调拨/货位扣除既有整托移动量。
-- 历史记录不能唯一匹配时保留待核对，不自动打印。
-- SQL 不依赖 JSON_VALUE / OPENJSON，兼容项目现用的应用侧 JSON 解析方式。

DECLARE @EndDate date = CAST(GETDATE() AS date);
DECLARE @StartDate date = DATEADD(day, -29, @EndDate);
DECLARE @MainID bigint = 0; -- 换成候选单据 ID，只执行对应单据类型的明细段。
DECLARE @OrderUuid nvarchar(200) = N''; -- 换成第 3 段返回的 pdaOrderUuid。
DECLARE @Barcode nvarchar(1000) = N''; -- 换成需要核对余额的 traceBackCode。

-- 1. 近 30 天全部 11 种单据候选（应用实际使用的 SQL）
WITH recent AS (SELECT 'CGDH' AS bill_type, v.ID, v.cCode AS bill_number, v.dDate AS bill_date FROM PU_ArrivalVouch v WHERE v.dDate >= @StartDate AND v.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM PU_ArrivalVouchs d WHERE d.ID = v.ID AND d.iQuantity > 0)
UNION ALL
SELECT 'CGRK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date FROM RdRecord01 r WHERE r.dDate >= @StartDate AND r.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '01' AND d.ID = r.ID AND d.iQuantity > 0)
UNION ALL
SELECT 'XSCK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date FROM RdRecord32 r WHERE r.dDate >= @StartDate AND r.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '32' AND d.ID = r.ID AND d.iQuantity < 0)
UNION ALL
SELECT 'CCPRK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date FROM RdRecord10 r WHERE r.dDate >= @StartDate AND r.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '10' AND d.ID = r.ID AND d.iQuantity > 0)
UNION ALL
SELECT 'OtherIN' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date FROM RdRecord08 r WHERE r.dDate >= @StartDate AND r.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '08' AND d.ID = r.ID AND d.iQuantity > 0)
UNION ALL
SELECT 'OtherOUT' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date FROM RdRecord09 r WHERE r.dDate >= @StartDate AND r.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '09' AND d.ID = r.ID AND d.iQuantity < 0)
UNION ALL
SELECT 'CLCK' AS bill_type, r.ID, r.cCode AS bill_number, r.dDate AS bill_date FROM RdRecord11 r WHERE r.dDate >= @StartDate AND r.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM rdall_yx d WHERE d.Class = '11' AND d.ID = r.ID AND d.iQuantity < 0)
UNION ALL
SELECT 'DBD' AS bill_type, a.ID, a.cTVCode AS bill_number, a.dTVDate AS bill_date FROM TransVouch a WHERE a.dTVDate >= @StartDate AND a.dTVDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM TransVouchs d WHERE d.ID = a.ID AND d.iTVQuantity > 0)
UNION ALL
SELECT 'PDD' AS bill_type, a.ID, a.cCVCode AS bill_number, a.dCVDate AS bill_date FROM CheckVouch a WHERE a.dCVDate >= @StartDate AND a.dCVDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM CheckVouchs d WHERE d.ID = a.ID AND d.iCVCQuantity > 0)
UNION ALL
SELECT 'XTZY' AS bill_type, a.ID, a.cAVCode AS bill_number, a.dAVDate AS bill_date FROM AssemVouch a WHERE a.dAVDate >= @StartDate AND a.dAVDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM AssemVouchs d WHERE d.ID = a.ID AND d.bAVType = N'转换后' AND d.iAVQuantity > 0)
UNION ALL
SELECT 'HWTZ' AS bill_type, a.ID, a.cVouchCode AS bill_number, a.dDate AS bill_date FROM AdjustPVouch a WHERE a.dDate >= @StartDate AND a.dDate < DATEADD(day, 1, @EndDate) AND EXISTS (SELECT 1 FROM AdjustPVouchs d WHERE d.ID = a.ID AND d.iQuantity > 0)) SELECT bill_type, ID, bill_number AS 单据号, bill_date AS 单据日期 FROM recent ORDER BY bill_date DESC, bill_number DESC;

-- 2. CGDH 采购到货单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
CAST(a.cWhCode AS NVARCHAR(50))            AS 仓库编码,
CAST(wh.cWhName AS NVARCHAR(50))           AS 仓库名称,

CAST('' AS NVARCHAR(50))           AS 货位编码,
CAST('' AS NVARCHAR(50))          AS 货位名称,

    a.cInvCode             AS 存货编码,
    inv.cInvName           AS 存货名称,

    a.iQuantity            AS 数量,
    COALESCE(docUnit.cComUnitName, unit.cComUnitName, N'') AS 单位,
    a.cBatch               AS 批号,
    inv.cPackingType       AS 包装方式
FROM PU_ArrivalVouchs a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
LEFT JOIN ComputationUnit docUnit
    ON a.cUnitID = docUnit.cComunitCode
LEFT JOIN Warehouse wh
    ON a.cWhCode = wh.cWhCode
WHERE
    a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. CGRK 采购入库单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(a.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(a.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    a.cInvCode       AS 存货编码,
    a.cInvName       AS 存货名称,

    a.iQuantity      AS 数量,
    COALESCE(NULLIF(a.cComUnitName, N''), unit.cComUnitName, N'') AS 单位,
    a.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM rdall_yx a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
WHERE
    a.Class = '01'
    AND a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. XSCK 销售出库单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(a.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(a.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    a.cInvCode       AS 存货编码,
    a.cInvName       AS 存货名称,

    a.iQuantity      AS 数量,
    COALESCE(NULLIF(a.cComUnitName, N''), unit.cComUnitName, N'') AS 单位,
    a.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM rdall_yx a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
WHERE
    a.Class = '32'
    AND a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. CCPRK 产成品入库单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(a.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(a.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    a.cInvCode       AS 存货编码,
    a.cInvName       AS 存货名称,

    a.iQuantity      AS 数量,
    COALESCE(NULLIF(a.cComUnitName, N''), unit.cComUnitName, N'') AS 单位,
    a.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM rdall_yx a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
WHERE
    a.Class = '10'
    AND a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. OtherIN 其他入库单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(a.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(a.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    a.cInvCode       AS 存货编码,
    a.cInvName       AS 存货名称,

    a.iQuantity      AS 数量,
    COALESCE(NULLIF(a.cComUnitName, N''), unit.cComUnitName, N'') AS 单位,
    a.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM rdall_yx a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
WHERE
    a.Class = '08'
    AND a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. OtherOUT 其他出库单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(a.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(a.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    a.cInvCode       AS 存货编码,
    a.cInvName       AS 存货名称,

    a.iQuantity      AS 数量,
    COALESCE(NULLIF(a.cComUnitName, N''), unit.cComUnitName, N'') AS 单位,
    a.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM rdall_yx a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
WHERE
    a.Class = '09'
    AND a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. CLCK 材料出库单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    a.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(a.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(a.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    a.cInvCode       AS 存货编码,
    a.cInvName       AS 存货名称,

    a.iQuantity      AS 数量,
    COALESCE(NULLIF(a.cComUnitName, N''), unit.cComUnitName, N'') AS 单位,
    a.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM rdall_yx a
LEFT JOIN Inventory inv
    ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
WHERE
    a.Class = '11'
    AND a.ID = @MainID
ORDER BY
    a.AutoID;

-- 2. DBD 调拨单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    b.AutoID AS 明细ID,
    CAST(ISNULL(a.cIWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(wh.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(b.cinposcode, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(ps.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    b.cInvCode        AS 存货编码,
    inv.cInvName        AS 存货名称,

    b.iTVQuantity     AS 数量,
    COALESCE(unit.cComUnitName, N'') AS 单位,
    b.cTVBatch        AS 批号,
    inv.cPackingType  AS 包装方式
FROM TransVouch a
LEFT JOIN TransVouchs b
    ON a.ID = b.ID
LEFT JOIN Inventory inv
    ON b.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
LEFT JOIN Warehouse wh
    ON a.cIWhCode = wh.cWhCode
LEFT JOIN Position ps
    ON b.cinposcode = ps.cPosCode
    AND ps.cWhCode = a.cIWhCode
WHERE
    a.ID = @MainID
ORDER BY
    b.AutoID;

-- 2. PDD 盘点单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    b.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(wh.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,
    CAST(COALESCE(NULLIF(b.cPosition, ''), a.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(ps.cPosName, '') AS NVARCHAR(50)) AS 货位名称,
    b.cInvCode AS 存货编码,
    inv.cInvName AS 存货名称,
    b.iCVCQuantity AS 数量,
    COALESCE(unit.cComUnitName, N'') AS 单位,
    b.cCVBatch AS 批号,
    inv.cPackingType AS 包装方式
FROM CheckVouch a
INNER JOIN CheckVouchs b
    ON a.ID = b.ID
LEFT JOIN Inventory inv
    ON b.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
LEFT JOIN Warehouse wh
    ON a.cWhCode = wh.cWhCode
LEFT JOIN Position ps
    ON COALESCE(NULLIF(b.cPosition, ''), a.cPosition) = ps.cPosCode
    AND ps.cWhCode = a.cWhCode
WHERE
    a.ID = @MainID
    AND b.iCVCQuantity > 0
ORDER BY
    b.autoID;

-- 2. XTZY 形态转换单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    b.AutoID AS 明细ID,
    CAST(ISNULL(b.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(wh.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(b.cPosition, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(ps.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    b.cInvCode        AS 存货编码,
    inv.cInvName        AS 存货名称,

    b.iAVQuantity     AS 数量,
    COALESCE(unit.cComUnitName, N'') AS 单位,
    b.cAVBatch        AS 批号,
    inv.cPackingType  AS 包装方式
FROM AssemVouch a
LEFT JOIN AssemVouchs b
    ON a.ID = b.ID
LEFT JOIN Inventory inv
    ON b.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
LEFT JOIN Warehouse wh
    ON b.cWhCode = wh.cWhCode
LEFT JOIN Position ps
    ON b.cPosition = ps.cPosCode
    AND ps.cWhCode = b.cWhCode
WHERE
    a.ID = @MainID
    AND b.bAVType = N'转换后'
ORDER BY
    b.AutoID;

-- 2. HWTZ 货位调整单 明细（应用实际单据明细 SQL）
SELECT
    a.ID AS 单据ID,
    b.AutoID AS 明细ID,
    CAST(ISNULL(a.cWhCode, '') AS NVARCHAR(50)) AS 仓库编码,
    CAST(ISNULL(wh.cWhName, '') AS NVARCHAR(50)) AS 仓库名称,

    CAST(ISNULL(b.cAPosCode, '') AS NVARCHAR(50)) AS 货位编码,
    CAST(ISNULL(ps.cPosName, '') AS NVARCHAR(50)) AS 货位名称,

    b.cInvCode       AS 存货编码,
    inv.cInvName       AS 存货名称,

    b.iQuantity      AS 数量,
    COALESCE(unit.cComUnitName, N'') AS 单位,
    b.cBatch         AS 批号,
    inv.cPackingType AS 包装方式
FROM AdjustPVouch a
LEFT JOIN AdjustPVouchs b
    ON a.ID = b.ID
LEFT JOIN Inventory inv
    ON b.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit unit
    ON inv.cComUnitCode = unit.cComunitCode
LEFT JOIN Warehouse wh
    ON a.cWhCode = wh.cWhCode
LEFT JOIN Position ps
    ON b.cAPosCode = ps.cPosCode
    AND ps.cWhCode = a.cWhCode
WHERE
    a.ID = @MainID
ORDER BY
    b.AutoID;

-- 3. 打印平台与 PDA 制单记录（应用实际第一阶段查询）
SELECT [json], pdaOrderUuid, CAST(orderType AS nvarchar(100)) AS orderType
FROM TraceBackOrder
WHERE CAST(orderType AS nvarchar(100)) IN (N'打印平台', N'调拨单', N'货位调整单');
-- 应用解析 documentNumber 或 CurrencyOrderData.U8.uploadErpCode 后，
-- 筛选候选单据 UUID，每批最多 200 个 UUID，继续查标签和物料关联。

-- 4. 已打印原始标签（应用批量 IN 参数，这里用单个 UUID 演示）
SELECT c.pdaOrderUuid, c.traceBackCode, c.sn, g.[json] AS goods_json
FROM TraceBackOnlyCode c
LEFT JOIN TraceBackGoods g ON g.pdaGoodsUuid = c.pdaGoodsUuid
WHERE c.pdaOrderUuid = @OrderUuid;
-- 标签数量取 traceBackCode 第 4 段；第 5 段必须与 sn 一致。
-- Goods.code、Attribute.batchNumber、warehouseCode、inventory.storageLocationCode
-- 必须与 U8 明细一致。新记录还需匹配 Order.labelPrintSource 的类型及两个 ID。

-- 5. 调拨/货位 PDA 扫描记录
SELECT c.pdaOrderUuid, c.pdaGoodsUuid, c.id, c.traceBackCode, g.[json] AS goods_json
FROM TraceBackOnlyCode c
LEFT JOIN TraceBackGoods g ON g.pdaGoodsUuid = c.pdaGoodsUuid
WHERE c.pdaOrderUuid = @OrderUuid;

-- 6. 原标签数量事件：按时间和 ID 计算移动前余额（不是首次打印数量）
SELECT c.id, c.traceBackCode, c.[sum], CAST(o.orderType AS nvarchar(100)) AS orderType
FROM TraceBackOnlyCode c
LEFT JOIN TraceBackOrder o ON o.pdaOrderUuid = c.pdaOrderUuid
WHERE c.traceBackCode = @Barcode
ORDER BY c.traceBackCode, c.[time], c.id;
-- 发货单/材料出库事件扣减原标签余额；未知非零事件保留待核对。
-- 对同一 PDA 物料组：本次移动数量等于移动前余额 => 整托，无需新标签；
-- 本次数量小于余额 => 零散，需要新标签；重复物料行无法定位则待核对。
