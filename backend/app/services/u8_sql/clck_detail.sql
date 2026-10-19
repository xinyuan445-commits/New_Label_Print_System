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
