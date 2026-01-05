from db import get_db
from werkzeug.security import generate_password_hash

def rescue():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 1. Force the System Company into existence
        cur.execute("INSERT INTO companies (id, name, subdomain) VALUES (1, 'Drugan Group HQ', 'admin') ON CONFLICT (id) DO NOTHING")
        
        # 2. Clear any half-broken admin user attempt
        cur.execute("DELETE FROM users WHERE email = 'admin@drugangroup.co.uk'")
        
        # 3. Insert fresh SuperAdmin
        pw_hash = generate_password_hash('password123')
        cur.execute("""
            INSERT INTO users (username, password_hash, email, role, company_id, name) 
            VALUES ('admin@drugangroup.co.uk', %s, 'admin@drugangroup.co.uk', 'SuperAdmin', 1, 'Super Admin')
        """, (pw_hash,))
        
        conn.commit()
        print("✅ ACCOUNT RESTORED. Login: admin@drugangroup.co.uk / Pass: password123")
        conn.close()
        
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    rescue()