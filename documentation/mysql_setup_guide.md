# MySQL Setup Guide — IPL Cricket Analytics

This guide covers creating the database user, configuring credentials safely, and building, loading and validating the database from scratch.

## 1. Requirements

| Item | Version used in this project |
|---|---|
| MySQL Server | 8.0 (Windows service `MySQL80`, port 3306) |
| Python | 3.12 with `pandas`, `mysql-connector-python` |
| Optional | MySQL Workbench 8.0 (to browse tables and run `sql/*.sql` by hand) |

## 2. Create a dedicated database user (one-time)

Don't use `root` for day-to-day analysis. Sign in to MySQL Workbench (or `mysql -u root -p`) as an administrator and run the statements below. Choose your own password, and don't save it in any project file except the git-ignored config described in step 3.

```sql
CREATE USER IF NOT EXISTS 'ipl_analyst'@'localhost' IDENTIFIED BY '<choose-a-strong-password>';
GRANT ALL PRIVILEGES ON ipl_cricket_analytics.* TO 'ipl_analyst'@'localhost';
FLUSH PRIVILEGES;
```

The user only has rights on the `ipl_cricket_analytics` schema. `CREATE DATABASE IF NOT EXISTS` in `sql/01_create_database.sql` works with this grant, because MySQL allows a user to create a database they have been granted privileges on.

## 3. Configure credentials (never committed)

Choose **one** of these options:

**Option A — local config file (recommended)**
1. Copy `config/mysql_config.example.ini` to `config/mysql_config.ini`.
2. Replace `CHANGE_ME` with the password.

`config/mysql_config.ini` is listed in `.gitignore`.

**Option B — environment variables** (these take priority over the file)

```bash
export MYSQL_USER=ipl_analyst
export MYSQL_PASSWORD='<your-password>'
```

On Windows PowerShell, use `$env:MYSQL_USER = 'ipl_analyst'` and so on.

The Python scripts never print or log the password. Reports only record the server version, user name, host and database.

## 4. Build, load and validate (run from the project root)

```bash
python python/04_load_mysql.py          # create DB + tables, load in one transaction, indexes, views
python python/04b_validate_mysql.py     # run sql/05_data_quality_checks.sql -> reports/sql_validation_report.md
python python/04c_run_sql_analysis.py   # run sql/06_business_analysis.sql -> reports/sql_query_results/, report
python python/04d_reconcile_sql_python.py  # SQL vs Python EDA -> reports/sql_python_reconciliation.csv
```

### What the loader does
1. Runs `sql/01_create_database.sql` and `sql/02_create_tables.sql`. Both are idempotent (`IF NOT EXISTS`).
2. Opens **one transaction**:
   - deletes existing rows (deliveries → matches → dimensions);
   - inserts dimensions, then matches, then deliveries in batches of 5,000;
   - compares row counts and run, wicket, super-over and legal-ball totals with the CSVs.

   It **commits only if every total matches**. Otherwise it rolls back and the database is left unchanged.
3. Creates the indexes in `sql/03_create_indexes.sql`, skipping any that already exist.
4. Creates or replaces the views in `sql/04_create_views.sql`.

Rerunning the loader gives the same result: there are no duplicate rows and the IDs are stable, because surrogate keys are assigned in alphabetical order.

### Session settings applied by the scripts
- `sql_mode = STRICT_ALL_TABLES, ...`: a malformed value raises an error instead of being silently truncated.
- `div_precision_increment = 30`: MySQL division and `AVG()` normally keep only 4 extra decimal places. Raising this lets SQL results reconcile exactly with Python.

## 5. Running SQL by hand (Workbench)

1. Open each script and run it in order: `sql/01` → `sql/06`.
2. `sql/03_create_indexes.sql` is not rerun-safe when run by hand, because MySQL 8 has no `CREATE INDEX IF NOT EXISTS`. Skip it if the indexes already exist. The Python loader handles this automatically.
3. Run `SET SESSION div_precision_increment = 30;` first if you want unrounded ratios to match Python exactly.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| `MySQL credentials not configured` | Complete step 3 |
| `Access denied for user` | Check the user, password and host (`'ipl_analyst'@'localhost'`) and the grant from step 2 |
| `Can't connect to MySQL server on 'localhost:3306'` | Start the `MySQL80` service (Services app, or `net start MySQL80` from an admin prompt) |
| Loader prints `ROLLBACK` | Read the printed totals; the database was not changed |
