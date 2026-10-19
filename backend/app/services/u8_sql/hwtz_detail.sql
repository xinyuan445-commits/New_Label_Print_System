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
