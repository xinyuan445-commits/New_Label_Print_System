SELECT
    a.ID,
    a.cCVCode AS 单据号,
    a.dCVDate AS 单据日期
FROM CheckVouch a
WHERE
    (@Code IS NULL OR a.cCVCode LIKE @Code)
    AND a.dCVDate >= @StartDate
    AND a.dCVDate < DATEADD(day, 1, @EndDate)
ORDER BY
    a.dCVDate DESC,
    a.cCVCode DESC;
