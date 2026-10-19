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
