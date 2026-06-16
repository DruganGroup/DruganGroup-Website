import os
import psycopg2
from werkzeug.security import generate_password_hash
from db import get_db

def factory_reset():
    print("⚠️ WARNING: INITIATING FACTORY RESET")
    print("Connecting to database...")
    
    conn = get_db()
    if not conn:
        print("❌ Failed to connect to database.")
        return
        
    cur = conn.cursor()
    
    try:
        print("1. Fetching all tables...")
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema='public' 
            AND table_type='BASE TABLE'
            AND table_name NOT LIKE 'pg_%'
        """)
        tables = [row[0] for row in cur.fetchall()]
        
        if not tables:
            print("No tables found. Schema might be empty.")
        else:
            print(f"Found {len(tables)} base tables. Truncating all data...")
            # Disable triggers/constraints during truncate to avoid FK issues
            truncate_query = f"TRUNCATE TABLE {', '.join(tables)} RESTART IDENTITY CASCADE;"
            cur.execute(truncate_query)
            print("✅ All data wiped successfully.")
            
        # 2. SEED DEFAULT PRICING PLANS
        print("2. Seeding Plans...")
        plans = [
            ("Bronze (Starter)", 49.00, 5, 2, 50, 1024, '["Estimates","Invoices","Portal"]', "price_1Pk1vCGpC9Q77Yv8q2sH3eWk"),
            ("Silver (Professional)", 99.00, 15, 10, 500, 5120, '["Estimates","Invoices","Portal","Fleet","ServiceDesk"]', "price_1Pk1voGpC9Q77Yv8tM0uF7Pj"),
            ("Gold (Enterprise)", 199.00, 50, 50, 2000, 20480, '["Estimates","Invoices","Portal","Fleet","ServiceDesk","WhiteLabel","RAMS","Compliance"]', "price_1Pk1wJGpC9Q77Yv8lO9nC2tZ"),
            ("Founder (Unlimited)", 0.00, 9999, 9999, 99999, 999999, '["Estimates","Invoices","Portal","Fleet","ServiceDesk","WhiteLabel","RAMS","Compliance"]', "price_founder_free")
        ]
        
        for p in plans:
            cur.execute("""
                INSERT INTO plans (name, price, max_users, max_vehicles, max_clients, max_storage, modules_enabled, stripe_price_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, p)
            
        print("✅ Plans seeded.")
        
        # Fetch Founder Plan ID
        cur.execute("SELECT id FROM plans WHERE name = 'Founder (Unlimited)'")
        founder_plan_id = cur.fetchone()[0]

        # 3. CREATE MASTER SUPER ADMIN (Nathan)
        print("3. Creating Master Super Admin...")
        super_admin_email = os.environ.get("SUPERADMIN_EMAIL", "nathan@businessbetter.co.uk")
        import random, string
        super_admin_pass = os.environ.get("SUPERADMIN_PASS")
        if not super_admin_pass:
            super_admin_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            print("⚠️ WARNING: SUPERADMIN_PASS not found in environment. Generated random password.")
        hashed_sa_pw = generate_password_hash(super_admin_pass)
        
        cur.execute("""
            INSERT INTO users (company_id, name, email, password_hash, role)
            VALUES (NULL, 'Super Admin', %s, %s, 'SuperAdmin')
        """, (super_admin_email, hashed_sa_pw))
        print("✅ Super Admin created.")

        # 4. CREATE DRUGAN GROUP TENANT (Info)
        print("4. Creating Drugan Group Tenant Account...")
        dg_email = os.environ.get("DEFAULT_TENANT_EMAIL", "info@drugangroup.co.uk")
        dg_pass = os.environ.get("DEFAULT_TENANT_PASS")
        if not dg_pass:
            dg_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
            print("⚠️ WARNING: DEFAULT_TENANT_PASS not found in environment. Generated random password.")
        hashed_dg_pw = generate_password_hash(dg_pass)
        
        cur.execute("""
            INSERT INTO companies (name, sub_domain, contact_email)
            VALUES ('Drugan Group', 'drugangroup', %s) RETURNING id
        """, (dg_email,))
        dg_company_id = cur.fetchone()[0]
        
        cur.execute("""
            INSERT INTO subscriptions 
            (company_id, plan_id, plan_tier, status, start_date, max_users, max_vehicles, max_clients, max_storage, modules) 
            VALUES (%s, %s, 'Founder (Unlimited)', 'Active', CURRENT_DATE, 9999, 9999, 99999, 999999, 'Estimates,Invoices,Portal,Fleet,ServiceDesk,WhiteLabel,RAMS,Compliance')
        """, (dg_company_id, founder_plan_id))
        
        cur.execute("""
            INSERT INTO users (company_id, name, email, password_hash, role)
            VALUES (%s, 'Nathan Drugan', %s, %s, 'Admin')
        """, (dg_company_id, dg_email, hashed_dg_pw))
        
        cur.execute("""
            INSERT INTO staff (company_id, name, email, position, status, pay_rate)
            VALUES (%s, 'Nathan Drugan', %s, 'Owner', 'Active', 0.00)
        """, (dg_company_id, dg_email))
        
        cur.execute("""
            INSERT INTO settings (company_id, key, value) VALUES 
            (%s, 'company_name', 'Drugan Group'),
            (%s, 'subscription_status', 'Active')
        """, (dg_company_id, dg_company_id))

        print("✅ Drugan Group Tenant created.")

        conn.commit()
        print("🎉 FACTORY RESET COMPLETE!")
        print(f"Super Admin Login: {super_admin_email} | Password: {super_admin_pass}")
        print(f"Tenant Admin Login: {dg_email} | Password: {dg_pass}")

    except Exception as e:
        conn.rollback()
        print(f"❌ FATAL ERROR: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    confirm = input("Type 'RESET' to completely wipe the database: ")
    if confirm == "RESET":
        factory_reset()
    else:
        print("Aborted.")
