from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 
DB_URL = os.environ.get("DATABASE_URL")

# --- DATABASE HELPER ---
def get_db():
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"DB Error: {e}")
        return None

# --- ROUTE: HOME ---
@app.route('/')
def home():
    return render_template('index.html')

# --- ROUTE: LOGIN (UPDATED FOR SaaS) ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_or_user = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        if not conn: return "DB Error"
        cur = conn.cursor()
        
        # We now check for the user AND fetch their company_id
        cur.execute("""
            SELECT id, username, role, company_id 
            FROM users 
            WHERE (username = %s OR email = %s) AND password_hash = %s
        """, (email_or_user, email_or_user, password))
        
        user = cur.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[2]
            session['company_id'] = user[3] # CRITICAL: We now know which 'Apartment' they live in
            
            # Redirect SuperAdmin to the Control Panel
            if user[2] == 'SuperAdmin':
                return redirect(url_for('super_admin_dashboard'))
            else:
                return redirect(url_for('client_dashboard')) # Or office dashboard
        else:
            flash('Invalid Login')

    return render_template('login.html')

# --- ROUTE: SUPER ADMIN DASHBOARD (THE CONTROL PANEL) ---
@app.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    # SECURITY GATE: Only SuperAdmins allowed
    if session.get('role') != 'SuperAdmin':
        return redirect(url_for('login'))
        
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        # 1. Capture Form Data
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        owner_pass = request.form.get('owner_pass')
        plan = request.form.get('plan') # 'Pro', 'Enterprise'
        
        try:
            # 2. Create Company
            cur.execute("INSERT INTO companies (name, contact_email) VALUES (%s, %s) RETURNING id", (comp_name, owner_email))
            new_company_id = cur.fetchone()[0]
            
            # 3. Create Subscription
            cur.execute("""
                INSERT INTO subscriptions (company_id, plan_tier, status) 
                VALUES (%s, %s, 'Active')
            """, (new_company_id, plan))
            
            # 4. Create Admin User for that Company
            cur.execute("""
                INSERT INTO users (username, password_hash, email, role, company_id)
                VALUES (%s, %s, %s, 'Admin', %s)
            """, (owner_email, owner_pass, owner_email, new_company_id))
            
            # 5. Inject Default Modules/Permissions for them
            # This ensures they have buttons when they log in!
            modules = [
                ('access_site_app', 'Site Companion', 1, '1.0'),
                ('access_finance', 'Finance Admin', 1, '1.0'),
                ('office', 'Office Hub', 1, '1.0')
            ]
            # Note: We need a way to link modules to companies. 
            # For now, we assume the 'modules' table is global? 
            # WAIT: In SaaS, permissions need to be per-company.
            # We will handle that logic later. For now, we just create the user.
            
            conn.commit()
            flash(f"✅ Success! {comp_name} created with ID {new_company_id}")
            
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    # Load List of Companies to show in the table
    cur.execute("""
        SELECT c.id, c.name, s.plan_tier, s.status, u.email 
        FROM companies c
        LEFT JOIN subscriptions s ON c.id = s.company_id
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin'
        ORDER BY c.id DESC
    """)
    companies = cur.fetchall()
    conn.close()
    
    return render_template('super_admin.html', companies=companies)

@app.route('/client-portal')
def client_dashboard():
    return f"<h1>Welcome {session.get('user_name')}</h1><p>Company ID: {session.get('company_id')}</p>"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)