from db import get_db

def run_upgrade():
    print("🚀 Connecting to Database...")
    conn = get_db()
    if not conn:
        print("❌ Failed to connect.")
        return

    cur = conn.cursor()
    try:
        # Add the Stripe columns safely
        print("⚙️ Adding Stripe columns to 'plans' table...")
        cur.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS stripe_product_id VARCHAR(100);")
        cur.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS stripe_price_id VARCHAR(100);")
        
        conn.commit()
        print("✅ SUCCESS: Database upgraded! You can now delete this file.")
    except Exception as e:
        conn.rollback()
        print(f"❌ Error: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    run_upgrade()