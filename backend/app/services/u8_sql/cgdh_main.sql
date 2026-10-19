SELECT
    v.ID,
    v.cCode  AS 单据号,
    v.dDate  AS 单据日期
FROM PU_ArrivalVouch v
WHERE
    (@Code IS NULL OR v.cCode LIKE @Code)
    AND v.dDate >= @StartDate
    AND v.dDate <= @EndDate
ORDER BY
    v.dDate DESC, v.cCode DESC
