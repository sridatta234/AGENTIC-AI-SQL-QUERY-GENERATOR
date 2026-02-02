# MySQL SQL Generation Rules & Best Practices

## Critical MySQL Syntax Rules

### 1. INSERT Statements
- **NO subqueries in VALUES clause**: `INSERT INTO t VALUES (1, (SELECT...))` ❌
- **Use INSERT...SELECT instead**: `INSERT INTO t SELECT 1, (SELECT...) UNION ALL SELECT 2, (SELECT...)` ✅
- **Column count must match**: Each SELECT in UNION must have same number of columns as INSERT list
- **Respect column order**: Use the exact order from INFORMATION_SCHEMA.COLUMNS (ORDINAL_POSITION)

### 2. DELETE Statements
- **Cannot DELETE from CTE**: `WITH cte AS (...) DELETE FROM cte` ❌
- **DELETE from actual table**: `DELETE FROM actual_table WHERE id IN (SELECT id FROM cte)` ✅
- **Always use WHERE clause**: Prevent accidental mass deletion
- **For duplicates**: Use ROW_NUMBER() in subquery to identify which rows to keep

### 3. UPDATE Statements
- **Cannot UPDATE CTE**: Similar to DELETE restriction
- **Use JOIN for complex updates**: `UPDATE t1 JOIN t2 ON ... SET t1.col = t2.col`
- **Always use WHERE clause**: Prevent accidental mass updates

### 4. Window Functions
- **Supported since MySQL 8.0**: ROW_NUMBER(), RANK(), DENSE_RANK(), NTILE()
- **PARTITION BY for grouping**: Use for "Top N per group" queries
- **Cannot use in WHERE directly**: Must wrap in subquery or CTE

### 5. Common Table Expressions (CTEs)
- **WITH clause supported since MySQL 8.0**
- **CTEs are read-only**: Cannot INSERT/UPDATE/DELETE from CTE
- **Recursive CTEs allowed**: Use `WITH RECURSIVE` for hierarchical data
- **Must be followed by SELECT/INSERT/UPDATE/DELETE**

### 6. JOIN Syntax
- **Prefer explicit JOIN**: Use `INNER JOIN`, `LEFT JOIN` instead of comma syntax
- **ON clause required**: Except for CROSS JOIN
- **Multiple JOINs**: Chain them, each with its own ON clause

### 7. Data Types
- **VARCHAR vs TEXT**: VARCHAR(n) for known max length, TEXT for large variable content
- **INT vs BIGINT**: INT for -2B to 2B, BIGINT for larger ranges
- **DATETIME vs TIMESTAMP**: DATETIME for absolute time, TIMESTAMP for auto-update
- **DECIMAL for money**: Use DECIMAL(10,2) not FLOAT for currency

### 8. Constraints
- **PRIMARY KEY**: Auto-creates unique index
- **FOREIGN KEY**: Requires referenced column to have index
- **UNIQUE**: Creates unique index
- **NOT NULL**: Cannot be NULL
- **DEFAULT**: Provides default value
- **CHECK**: Validates data (MySQL 8.0.16+)

### 9. Indexes
- **Composite indexes**: Order matters - most selective column first
- **Covering indexes**: Include all columns used in query
- **Full-text indexes**: For text search, use MATCH...AGAINST
- **Spatial indexes**: For geometry data types

### 10. Transactions
- **START TRANSACTION**: Begin transaction
- **COMMIT**: Save changes
- **ROLLBACK**: Undo changes
- **SAVEPOINT**: Create rollback point within transaction

### 11. String Functions
- **CONCAT()**: Join strings, NULL-safe
- **CONCAT_WS()**: Join with separator
- **SUBSTRING()**: Extract substring
- **REPLACE()**: Replace text
- **TRIM(), LTRIM(), RTRIM()**: Remove whitespace

### 12. Date/Time Functions
- **NOW()**: Current datetime
- **CURDATE()**: Current date
- **DATE_ADD()**, **DATE_SUB()**: Add/subtract intervals
- **DATEDIFF()**: Days between dates
- **YEAR()**, **MONTH()**, **DAY()**: Extract parts

### 13. Aggregate Functions
- **COUNT()**: Count rows
- **SUM()**: Sum values
- **AVG()**: Average
- **MIN()**, **MAX()**: Minimum/maximum
- **GROUP_CONCAT()**: Concatenate grouped values

### 14. Subqueries
- **Scalar subquery**: Returns single value, can use in SELECT/WHERE
- **Row subquery**: Returns single row
- **Table subquery**: Returns multiple rows, use with IN/EXISTS
- **Correlated subquery**: References outer query

### 15. LIMIT and OFFSET
- **LIMIT n**: Return first n rows
- **LIMIT n OFFSET m**: Skip m rows, return n rows
- **LIMIT m, n**: Alternative syntax (skip m, return n)

## Common Pitfalls to Avoid

1. **Implicit type conversion**: Can prevent index usage
2. **SELECT * in production**: Specify columns explicitly
3. **N+1 query problem**: Use JOINs instead of loops
4. **Missing indexes on foreign keys**: MySQL doesn't auto-create them
5. **Using OR in WHERE**: Can prevent index usage, consider UNION instead
6. **Comparing NULL with =**: Use IS NULL or IS NOT NULL
7. **String comparison case sensitivity**: Depends on collation (utf8mb4_general_ci is case-insensitive)

## Performance Best Practices

1. **Use EXPLAIN**: Analyze query execution plan
2. **Index foreign keys**: Always index columns used in JOINs
3. **Avoid functions on indexed columns**: `WHERE YEAR(date) = 2022` prevents index use
4. **Use covering indexes**: Include all columns in SELECT and WHERE
5. **Partition large tables**: By date or other logical grouping
6. **Avoid SELECT DISTINCT**: Often indicates poor schema design
7. **Use LIMIT**: For pagination and testing
8. **Batch inserts**: Use multi-row INSERT or LOAD DATA INFILE

## MySQL Version Considerations

- **MySQL 5.7**: No window functions, limited JSON support
- **MySQL 8.0+**: Window functions, CTEs, CHECK constraints, improved JSON
- **MySQL 8.0.19+**: Multi-valued indexes for JSON arrays
- **MySQL 8.0.20+**: Hash join optimization

## References
- Official MySQL Documentation: https://dev.mysql.com/doc/refman/8.0/en/
- MySQL Performance Blog: https://www.percona.com/blog/
- Use The Index, Luke: https://use-the-index-luke.com/
