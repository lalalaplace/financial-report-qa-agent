SELECT target_table, COUNT(*) AS cnt
FROM attachment3_extract_result
WHERE extract_method = 'rule'
GROUP BY target_table
ORDER BY target_table;

SELECT
    file_id,
    target_table,
    COUNT(*) AS cnt
FROM attachment3_extract_result
WHERE extract_method = 'rule'
GROUP BY file_id, target_table
ORDER BY file_id, target_table;

SELECT
    r.file_id,
    d.target_table,
    d.field_code,
    d.field_name_cn
FROM report_file_index r
JOIN attachment3_field_dict d
  ON 1=1
LEFT JOIN attachment3_extract_result e
  ON e.file_id = r.file_id
 AND e.target_table = d.target_table
 AND e.field_code = d.field_code
WHERE COALESCE(r.is_summary, FALSE) = FALSE
  AND e.result_id IS NULL
ORDER BY r.file_id, d.target_table, d.sort_order;