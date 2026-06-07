"""
One-off utility: dump the full database schema (tables + columns) to schema.txt
Run:  python dump_schema.py
Then open schema.txt and share its contents.
This uses psycopg2 (already installed) so no pg_dump needed.
"""
import psycopg2

# Render EXTERNAL database URL
DB_URL = "postgresql://tradecoredb_ulzt_user:gfi8uuIDdNn3juUELdGg361sDMHwKub2@dpg-d57vom4hg0os73bgt8g0-a.frankfurt-postgres.render.com/tradecore_db"

OUT_FILE = "schema.txt"


def main():
    conn = psycopg2.connect(DB_URL, sslmode="require")
    cur = conn.cursor()

    # Get all tables in the public schema
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
        ORDER BY table_name;
    """)
    tables = [r[0] for r in cur.fetchall()]

    lines = []
    lines.append(f"DATABASE SCHEMA DUMP — {len(tables)} tables\n")
    lines.append("=" * 60 + "\n")

    for t in tables:
        lines.append(f"\nTABLE: {t}\n")
        lines.append("-" * 60 + "\n")

        # Columns + types + nullability + defaults
        cur.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position;
        """, (t,))
        for col, dtype, nullable, default in cur.fetchall():
            null_txt = "NULL" if nullable == "YES" else "NOT NULL"
            def_txt = f" DEFAULT {default}" if default else ""
            lines.append(f"  {col:<28} {dtype:<20} {null_txt}{def_txt}\n")

        # Row count (handy for context)
        try:
            cur.execute(f'SELECT COUNT(*) FROM "{t}"')
            count = cur.fetchone()[0]
            lines.append(f"  [rows: {count}]\n")
        except Exception:
            conn.rollback()

    conn.close()

    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.writelines(lines)

    print(f"Done. Wrote schema for {len(tables)} tables to {OUT_FILE}")
    print("Open schema.txt and paste its contents back.")


if __name__ == "__main__":
    main()
