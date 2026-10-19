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
