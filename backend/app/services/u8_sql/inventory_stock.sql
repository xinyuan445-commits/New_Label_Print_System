SELECT CAST('current' AS varchar(8)) AS source, a.AutoID AS stock_id,
       a.cWhCode AS warehouse_code, wh.cWhName AS warehouse_name,
       CAST('' AS nvarchar(100)) AS location_code,
       CAST('' AS nvarchar(200)) AS location_name,
       a.cInvCode AS item_code, inv.cInvName AS item_name,
       inv.cInvStd AS specification, cp.cComUnitName AS unit,
       a.iQuantity AS quantity, a.cBatch AS batch
FROM CurrentStock a
JOIN Warehouse wh ON a.cWhCode = wh.cWhCode
LEFT JOIN Inventory inv ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit cp ON inv.cComUnitCode = cp.cComunitCode
WHERE wh.bWhPos = 0 AND a.iQuantity > 0 AND wh.dWhEndDate IS NULL
UNION ALL
SELECT CAST('position' AS varchar(8)) AS source, a.Autoid AS stock_id,
       a.cWhCode AS warehouse_code, wh.cWhName AS warehouse_name,
       a.cPosCode AS location_code, ps.cPosName AS location_name,
       a.cInvCode AS item_code, inv.cInvName AS item_name,
       inv.cInvStd AS specification, cp.cComUnitName AS unit,
       a.iQuantity AS quantity, a.cBatch AS batch
FROM InvPositionSum a
JOIN Warehouse wh ON a.cWhCode = wh.cWhCode
LEFT JOIN Inventory inv ON a.cInvCode = inv.cInvCode
LEFT JOIN ComputationUnit cp ON inv.cComUnitCode = cp.cComunitCode
LEFT JOIN Position ps ON a.cPosCode = ps.cPosCode AND a.cWhCode = ps.cWhCode
WHERE wh.bWhPos = 1 AND a.iQuantity > 0 AND wh.dWhEndDate IS NULL
