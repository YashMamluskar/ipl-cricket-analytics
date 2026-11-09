"""
Shared MySQL helpers for Phase 4.

Credentials are NEVER hard-coded or printed. Resolution order:
  1. Environment variables MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
  2. config/mysql_config.ini  (git-ignored; copy from config/mysql_config.example.ini)
"""
from __future__ import annotations

import configparser
import os
import re
from pathlib import Path

import mysql.connector
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SQL_DIR = PROJECT_ROOT / "sql"
CONFIG_FILE = PROJECT_ROOT / "config" / "mysql_config.ini"
DB_NAME = "ipl_cricket_analytics"


def load_config() -> dict:
    cfg = {"host": "localhost", "port": 3306, "user": None, "password": None, "database": DB_NAME}
    if CONFIG_FILE.exists():
        cp = configparser.ConfigParser()
        cp.read(CONFIG_FILE, encoding="utf-8")
        if "mysql" in cp:
            for k in cfg:
                if k in cp["mysql"]:
                    cfg[k] = cp["mysql"][k]
    for k in cfg:
        env = os.environ.get(f"MYSQL_{k.upper()}")
        if env:
            cfg[k] = env
    cfg["port"] = int(cfg["port"])
    if not cfg["user"] or cfg["password"] in (None, "", "CHANGE_ME"):
        raise RuntimeError(
            "MySQL credentials not configured. Copy config/mysql_config.example.ini to "
            "config/mysql_config.ini and fill in user/password, or set MYSQL_USER / MYSQL_PASSWORD. "
            "See documentation/mysql_setup_guide.md.")
    return cfg


def connect(with_database: bool = True):
    c = load_config()
    kwargs = dict(host=c["host"], port=c["port"], user=c["user"], password=c["password"],
                  charset="utf8mb4", collation="utf8mb4_0900_as_cs", autocommit=False, use_pure=True)
    if with_database:
        kwargs["database"] = c["database"]
    conn = mysql.connector.connect(**kwargs)
    cur = conn.cursor()
    # Strict mode: malformed values raise errors instead of being silently truncated/converted.
    cur.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES,ONLY_FULL_GROUP_BY,NO_ZERO_DATE,"
                "NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
    # MySQL's '/' and AVG() on integers return DECIMAL with only 4 extra digits by default.
    # Use the maximum (30) so SQL vs Python reconciliation compares true values, not rounding.
    cur.execute("SET SESSION div_precision_increment = 30")
    cur.close()
    return conn


def describe_connection(conn) -> dict:
    """Non-secret connection facts for reports (never includes the password)."""
    cur = conn.cursor()
    cur.execute("SELECT VERSION(), CURRENT_USER(), @@hostname, @@port, DATABASE()")
    v, u, h, p, db = cur.fetchone()
    cur.close()
    return {"mysql_version": v, "current_user": u, "server_host": h, "port": p, "database": db}


def split_sql(text: str) -> list[str]:
    """Split a .sql file into statements on ';' at end of line, ignoring -- comments.
    (Our scripts contain no stored routines, so no DELIMITER handling is needed.)"""
    lines = [ln for ln in text.splitlines() if not ln.strip().startswith("--")]
    body = "\n".join(lines)
    return [s.strip() for s in re.split(r";\s*(?:\n|$)", body) if s.strip()]


def run_sql_file(conn, name: str, skip_existing_indexes: bool = False) -> int:
    cur = conn.cursor()
    n = 0
    for stmt in split_sql((SQL_DIR / name).read_text(encoding="utf-8")):
        m = re.match(r"CREATE\s+INDEX\s+(\w+)\s+ON\s+(\w+)", stmt, re.I)
        if skip_existing_indexes and m:
            cur.execute("SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema = DATABASE() "
                        "AND table_name = %s AND index_name = %s", (m.group(2), m.group(1)))
            if cur.fetchone()[0]:
                continue
        cur.execute(stmt)
        if cur.with_rows:
            cur.fetchall()
        n += 1
    conn.commit()
    cur.close()
    return n


def query_df(conn, sql: str, params=None) -> pd.DataFrame:
    cur = conn.cursor()
    cur.execute(sql, params or ())
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    cur.close()
    df = pd.DataFrame(rows, columns=cols)
    # DECIMAL -> int when every value is whole (e.g. SUM of integers), else float
    for c in df.columns:
        if df[c].map(lambda v: type(v).__name__ == "Decimal").any():
            f = df[c].astype(float)
            df[c] = f.astype("Int64") if (f.dropna() % 1 == 0).all() else f
    return df
