SELECT
    a.ID,
    a.cVouchCode AS 单据号,
    a.dDate      AS 单据日期
FROM AdjustPVouch a
WHERE
    (@Code IS NULL OR a.cVouchCode LIKE @Code)
    AND a.dDate >= @StartDate
    AND a.dDate <= @EndDate
ORDER BY
    a.dDate DESC,
    a.cVouchCode DESC;
