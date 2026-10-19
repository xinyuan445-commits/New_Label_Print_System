SELECT
    a.ID,
    a.cTVCode AS 单据号,
    a.dTVDate AS 单据日期
FROM TransVouch a
WHERE
    (@Code IS NULL OR a.cTVCode LIKE @Code)
    AND a.dTVDate >= @StartDate
    AND a.dTVDate <= @EndDate
ORDER BY
    a.dTVDate DESC,
    a.cTVCode DESC;
