import random
from datetime import date, timedelta
try:
    from faker import Faker
except ImportError:
    print("❌ Error: Faker is not installed. Please run: python -m pip install faker")
    exit()

from db import get_db
from app import app
from werkzeug.security import generate_password_hash

fake = Faker('en_GB')

def create_company_data(conn, cur, config):
    print(f"\n🚀 Starting build for: {config['name']} ({config['plan']})...")

    # 1. CREATE COMPANY
    cur.execute("INSERT INTO companies (name, subdomain, contact_email) VALUES (%s, %s, %s) RETURNING id", 
                (config['name'], config['slug'], config['email']))
    comp_id = cur.fetchone()[0]
    
    # 2. ASSIGN PLAN
    cur.execute("""
        INSERT INTO subscriptions (company_id, plan_tier, status, start_date) 
        VALUES (%s, %s, 'Active', CURRENT_DATE)
    """, (comp_id, config['plan']))

    # 3. CREATE SETTINGS
    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'currency_symbol', '£')", (comp_id,))
    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'vat_registered', 'yes')", (comp_id,))
    cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'country_code', 'UK')", (comp_id,))

    # 4. CREATE ADMIN USER
    admin_pass = generate_password_hash("password123")
    cur.execute("""
        INSERT INTO users (username, email, password_hash, role, company_id, name) 
        VALUES (%s, %s, %s, 'Admin', %s, 'Admin User')
    """, (config['email'], config['email'], admin_pass, comp_id))

    # 5. CREATE STAFF
    print(f"   - Hiring {config['staff_count']} Staff...")
    roles = ['Engineer', 'Office', 'Manager', 'Apprentice']
    for _ in range(config['staff_count']):
        cur.execute("""
            INSERT INTO staff (company_id, name, email, phone, position, status, pay_rate, pay_model)
            VALUES (%s, %s, %s, %s, %s, 'Active', %s, 'Hour')
        """, (comp_id, fake.name(), fake.email(), fake.phone_number(), random.choice(roles), random.randint(15, 45)))

    # 6. CREATE FLEET
    print(f"   - Buying {config['vehicle_count']} Vans...")
    models = ['Ford Transit', 'Mercedes Sprinter', 'VW Transporter', 'Vauxhall Vivaro']
    for i in range(config['vehicle_count']):
        mot_date = date.today() + timedelta(days=random.randint(-30, 300))
        cur.execute("""
            INSERT INTO vehicles (company_id, reg_plate, make_model, status, mot_due, tax_due, insurance_due, service_due, daily_cost)
            VALUES (%s, %s, %s, 'Active', %s, %s, %s, %s, 25.00)
        """, (comp_id, fake.license_plate(), random.choice(models), mot_date, mot_date, mot_date, mot_date))

    # 7. CREATE CLIENTS & PROPERTIES
    print(f"   - Acquiring {config['client_count']} Clients...")
    for _ in range(config['client_count']):
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, billing_address, status)
            VALUES (%s, %s, %s, %s, %s, 'Active') RETURNING id
        """, (comp_id, fake.company(), fake.company_email(), fake.phone_number(), fake.address()))
        client_id = cur.fetchone()[0]

        for _ in range(random.randint(1, 2)):
            gas_expiry = date.today() + timedelta(days=random.randint(-10, 365))
            cur.execute("""
                INSERT INTO properties (company_id, client_id, address_line1, postcode, tenant_name, gas_safety_due)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (comp_id, client_id, fake.street_address(), fake.postcode(), fake.name(), gas_expiry))

    # 8. CREATE FINANCE DATA
    print(f"   - generating {config['invoice_count']} Invoices...")
    for _ in range(config['invoice_count']):
        amount = random.randint(150, 5000)
        cur.execute("""
            INSERT INTO transactions (company_id, date, type, category, description, amount, reference)
            VALUES (%s, CURRENT_DATE - %s, 'Income', 'Sales', 'Invoice Payment', %s, %s)
        """, (comp_id, random.randint(0, 60), amount, f"INV-{random.randint(1000,9999)}"))

    conn.commit()
    print(f"✅ FINISHED: {config['name']} (ID: {comp_id})")
    print(f"   👉 Login: {config['email']} / password123")

def run_seed():
    with app.app_context():
        conn = get_db()
        cur = conn.cursor()
        
        # --- DEFINITION OF NEW COMPANIES ---
        companies = [
            {
                'name': 'Prestige Plumbing & Heating',
                'slug': 'prestige',
                'email': 'admin@prestige.com',
                'plan': 'Pro',  # Mid Tier
                'staff_count': 6,
                'vehicle_count': 4,
                'client_count': 15,
                'invoice_count': 12
            },
            {
                'name': 'Sparky Solutions',
                'slug': 'sparky',
                'email': 'admin@sparky.com',
                'plan': 'Starter', # Basic Tier
                'staff_count': 2,
                'vehicle_count': 1,
                'client_count': 3,
                'invoice_count': 5
            }
        ]

        try:
            for conf in companies:
                create_company_data(conn, cur, conf)
        except Exception as e:
            conn.rollback()
            print(f"❌ Error: {e}")
        finally:
            conn.close()

if __name__ == '__main__':
    run_seed()