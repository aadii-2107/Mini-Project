import argparse
import os
import sqlite3
import sys

import psycopg2


CREATE_PERSONS_SQL = """
CREATE TABLE IF NOT EXISTS persons (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
)
"""


def read_sqlite_persons(sqlite_path: str) -> list[dict]:
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT id, name, created_at FROM persons ORDER BY id ASC").fetchall()
        return [{"id": row["id"], "name": row["name"], "created_at": row["created_at"]} for row in rows]
    finally:
        conn.close()


def ensure_postgres_schema(pg_conn) -> None:
    cur = pg_conn.cursor()
    cur.execute(CREATE_PERSONS_SQL)
    pg_conn.commit()


def upsert_person(pg_conn, name: str, created_at: str) -> int | None:
    cur = pg_conn.cursor()
    cur.execute(
        """
        INSERT INTO persons (name, created_at)
        VALUES (%s, %s)
        ON CONFLICT (name)
        DO UPDATE SET created_at = EXCLUDED.created_at
        RETURNING id
        """,
        (name, created_at),
    )
    row = cur.fetchone()
    pg_conn.commit()
    return row[0] if row else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", default="project.db")
    parser.add_argument("--postgres-url", default="")
    args = parser.parse_args(argv)

    sqlite_path = args.sqlite_path
    postgres_url = args.postgres_url.strip() or (os.getenv("DATABASE_URL") or "").strip()
    if not postgres_url:
        raise SystemExit("PostgreSQL URL missing. Pass --postgres-url or set DATABASE_URL.")

    persons = read_sqlite_persons(sqlite_path)
    if not persons:
        print("No persons found in SQLite.", flush=True)
        return 0

    pg_conn = psycopg2.connect(postgres_url)
    try:
        ensure_postgres_schema(pg_conn)
        inserted = 0
        updated = 0
        for person in persons:
            name = str(person["name"] or "").strip()
            created_at = str(person["created_at"] or "").strip()
            if not name or not created_at:
                continue

            cur = pg_conn.cursor()
            cur.execute("SELECT id FROM persons WHERE LOWER(name) = LOWER(%s)", (name,))
            exists = cur.fetchone() is not None

            upsert_person(pg_conn, name, created_at)
            if exists:
                updated += 1
            else:
                inserted += 1

        print(f"Migration complete. Inserted: {inserted}, Updated: {updated}", flush=True)
        return 0
    finally:
        pg_conn.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
