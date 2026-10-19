SELECT
    a.ID,
    a.cAVCode AS 单据号,
    a.dAVDate AS 单据日期
FROM AssemVouch a
WHERE
    (@Code IS NULL OR a.cAVCode LIKE @Code)
    AND a.dAVDate >= @StartDate
    AND a.dAVDate <= @EndDate
ORDER BY
    a.dAVDate DESC,
    a.cAVCode DESC;
