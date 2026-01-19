import psycopg2
import os
from db import get_db

def fix_access_permissions():
    conn = get_db()
    if not conn:
        print("❌ DB Connection Failed")
        return

    try:
        cur = conn.cursor()
        print("🔓 Unlocking Demo Account Features...")

        # 1. Get the Demo Company ID
        cur.execute("SELECT id FROM companies WHERE name = 'Business Better Demo'")
        res = cur.fetchone()
        if not res:
            print("❌ Could not find 'Business Better Demo' company. Run create_demo_data.py first.")
            return
        company_id = res[0]

        # 2. Update User Role to 'owner' (Capitalized and lowercase just to be safe)
        # We set it to 'owner' which is usually the super-user in these systems
        cur.execute("UPDATE users SET role = 'owner' WHERE email = 'demo@businessbetter.co.uk'")
        print("   ✅ User promoted to 'owner'")

        # 3. Inject Active Modules
        # We first check what columns the 'modules' table has to avoid crashing
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'modules'")
        columns = [row[0] for row in cur.fetchall()]
        
        print(f"   ℹ️ Modules table columns: {columns}")

        # List of modules to unlock
        modules_list = ['finance', 'office', 'site', 'hr', 'compliance', 'crm']

        # We construct a query based on the columns we found
        # Usually tables are (company_id, module_name, status) OR (company_id, name, is_active)
        
        if 'module_name' in columns and 'status' in columns:
            print("   👉 Injecting modules (Standard Format)...")
            for mod in modules_list:
                cur.execute("""
                    INSERT INTO modules (company_id, module_name, status)
                    VALUES (%s, %s, 'active')
                    ON CONFLICT DO NOTHING
                """, (company_id, mod))

        elif 'name' in columns and 'status' in columns:
            print("   👉 Injecting modules (Name Format)...")
            for mod in modules_list:
                cur.execute("""
                    INSERT INTO modules (company_id, name, status)
                    VALUES (%s, %s, 'active')
                    ON CONFLICT DO NOTHING
                """, (company_id, mod))
                
        else:
            # Fallback: Just print the columns so we can fix it manually if this fails
            print("   ⚠️ Unknown Module Table Structure. Attempting generic insert...")
            try:
                 for mod in modules_list:
                    cur.execute(f"INSERT INTO modules (company_id, name, status) VALUES ({company_id}, '{mod}', 'active')")
            except Exception as e:
                print(f"   ❌ Module insert failed: {e}")

        conn.commit()
        print("🚀 SUCCESS! Log out and Log back in.")

    except Exception as e:
        print(f"❌ Critical Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    fix_access_permissions()