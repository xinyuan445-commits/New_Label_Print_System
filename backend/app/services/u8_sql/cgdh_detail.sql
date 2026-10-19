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
