SELECT
    r.ID,
    r.cCode AS 单据号,
    r.dDate AS 单据日期
FROM RdRecord08 r
WHERE
    (@Code IS NULL OR r.cCode LIKE @Code)
    AND r.dDate >= @StartDate
    AND r.dDate <= @EndDate
ORDER BY
    r.dDate DESC,
    r.cCode DESC;
