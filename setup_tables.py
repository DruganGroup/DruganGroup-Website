import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

def create_tables():
    db_url = os.environ.get("DATABASE_URL")
    if db_url:
        conn = psycopg2.connect(db_url, sslmode='require')
    else:
        conn = psycopg2.connect(
            dbname=os.environ.get("DB_NAME", "businessbetter"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", ""),
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432")
        )
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS property_documents (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                property_id INTEGER,
                document_type VARCHAR(100),
                filepath TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by INTEGER
            )
        """)
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS quote_documents (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                quote_id INTEGER,
                document_type VARCHAR(100),
                filepath TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by INTEGER
            )
        """)
        conn.commit()
        print("Tables created successfully.")
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == '__main__':
    create_tables()
