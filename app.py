from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import os

app = Flask(__name__)
# Secure secret key
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 

# --- DATABASE CONNECTION ---
DB_URL = os.environ.get("DATABASE_URL")

def get_db():
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

# --- MAIN STATIC PAGES ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/about')
@app.route('/about.html')
def about(): return render_template('about.html')

@app.route('/services')
@app.route('/services.html')
def services(): return render_template('services.html')

@app.route('/tradecore')
@app.route('/tradecore.html')
def tradecore(): return render_template('tradecore.html')

@app.route('/forensics')
@app.route('/forensics.html')
def forensics(): return render_template('forensics.html')

@app.route('/contact')
@app.route('/contact.html')
def contact(): return render_template('contact.html')

# --- SERVICE SUB-PAGES ---
@app.route('/roofing.html')
def roofing(): return render_template('roofing.html')

@app.route('/construction.html')
def construction(): return render_template('construction.html')

@app.route('/groundworks.html')
def groundworks(): return render_template('groundworks.html')

@app.route('/landscaping.html')
def landscaping(): return render_template('landscaping.html')

@app.route('/maintenance.html')
def maintenance(): return render_template('maintenance.html')

@app.route('/management.html')
def management(): return render_template('management.html')


# --- LOGIN SYSTEM ---
@app.route('/login', methods=['GET', 'POST'])
@app.route('/login.html', methods=['GET', 'POST']) 
def login():
    if request.method == 'POST':
        email_or_user = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        if not conn: 
            flash("System Error: Database Connection Failed")
            return render_template('login.html')
            
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, username, role, company_id 
                FROM users 
                WHERE (username = %s OR email = %s) AND password_hash = %s
            """, (email_or_user, email_or_user, password))
            user = cur.fetchone()
        except Exception as e:
            print(f"Query Error: {e}")
            user = None
        finally:
            conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[2]
            session['company_id'] = user[3]
            
            if user[2] == 'SuperAdmin':
                return redirect(url_for('super_admin_dashboard'))
            else:
                return redirect(url_for('main_launcher'))
        else:
            flash('Invalid Email or Password')

    return render_template('login.html')

# --- THE MAIN LAUNCHER (3 BUTTON MENU) ---
@app.route('/dashboard-menu')
def main_launcher():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('main_launcher.html', role=session.get('role'))


# --- CLIENT DASHBOARD (OFFICE HUB) ---
@app.route('/client-portal')
def client_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    company_id = session.get('company_id')
    
    conn = get_db()
    if not conn: return "DB Error"
    cur = conn.cursor()
    
    # Create tables if they don't exist yet
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            date DATE,
            type TEXT, 
            category TEXT, 
            description TEXT, 
            amount DECIMAL(10,2), 
            reference TEXT
        );
    """)
    conn.commit()

    # Calculate Totals
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    
    balance = income - expense

    # Get Recent Transactions
    cur.execute("""
        SELECT date, type, category, description, amount, reference 
        FROM transactions 
        WHERE company_id = %s 
        ORDER BY date DESC LIMIT 10
    """, (company_id,))
    transactions = cur.fetchall()
    
    conn.close()

    return render_template('client_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           total_balance=balance,
                           transactions=transactions)


# --- FINANCE DASHBOARD ---
@app.route('/finance-dashboard')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    if session.get('role') not in ['Admin', 'SuperAdmin']:
        return "Access Denied: You need Admin privileges to view Finance."

    company_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            date DATE,
            type TEXT, category TEXT, description TEXT, amount DECIMAL(10,2), reference TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    balance = income - expense

    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (company_id,))
    transactions = cur.fetchall()
    
    cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
    comp_row = cur.fetchone()
    session['company_name'] = comp_row[0] if comp_row else "My Company"

    conn.close()
    return render_template('finance_dashboard.html', total_income=income, total_expense=expense, total_balance=balance, transactions=transactions)


# --- HR & STAFF ROUTES ---
@app.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            name TEXT, position TEXT, dept TEXT, pay_rate DECIMAL(10,2), pay_model TEXT, access_level TEXT
        );
    """)
    conn.commit()

    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level FROM staff WHERE company_id = %s ORDER BY name", (session.get('company_id'),))
    staff = cur.fetchall()
    conn.close()
    
    return render_template('finance_hr.html', staff=staff)

@app.route('/finance/hr/add', methods=['POST'])
def add_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    name = request.form.get('name')
    position = request.form.get('position')
    dept = request.form.get('dept')
    rate = request.form.get('rate') or 0
    model = request.form.get('model')
    access = request.form.get('access_level')
    comp_id = session.get('company_id')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, name, position, dept, rate, model, access))
        
        if access != "None":
            username = name.split(" ")[0].lower() + f"{comp_id}" # e.g. john51
            email_fake = f"{username}@tradecore.com"
            default_pass = "Password123!" 
            
            cur.execute("SELECT id FROM users WHERE username=%s", (username,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO users (username, email, password_hash, role, company_id)
                    VALUES (%s, %s, %s, %s, %s)
                """, (username, email_fake, default_pass, access, comp_id))
                flash(f"✅ Staff added! Login: {username} / Pass: {default_pass}")
            else:
                flash("✅ Staff added, but username already existed.")
        else:
            flash("✅ Staff added successfully.")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('finance_hr'))

@app.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit()
    conn.close()
    flash("Staff deleted.")
    return redirect(url_for('finance_hr'))


# --- SUPER ADMIN DASHBOARD ---
@app.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('login'))
        
    conn = get_db()
    if not conn: return "Database Error"
    cur = conn.cursor()
    
    if request.method == 'POST':
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        owner_pass = request.form.get('owner_pass')
        plan = request.form.get('plan')
        
        try:
            cur.execute("INSERT INTO companies (name, contact_email) VALUES (%s, %s) RETURNING id", (comp_name, owner_email))
            new_company_id = cur.fetchone()[0]
            cur.execute("INSERT INTO subscriptions (company_id, plan_tier, status) VALUES (%s, %s, 'Active')", (new_company_id, plan))
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, 'Admin', %s)", (owner_email, owner_pass, owner_email, new_company_id))
            conn.commit()
            flash(f"✅ Success! {comp_name} created.")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    cur.execute("SELECT c.id, c.name, s.plan_tier, s.status, u.email FROM companies c LEFT JOIN subscriptions s ON c.id = s.company_id LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin' ORDER BY c.id DESC")
    companies = cur.fetchall()
    conn.close()
    return render_template('super_admin.html', companies=companies)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))
    
# --- FLEET ROUTES ---
@app.route('/finance/fleet')
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    # Create Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            reg_plate TEXT,
            make_model TEXT,
            daily_cost DECIMAL(10,2),
            mot_due DATE,
            tax_due DATE,
            service_due DATE,
            status TEXT,
            tracker_url TEXT
        );
    """)
    conn.commit()
    
    # Fetch Data
    cur.execute("SELECT id, reg_plate, make_model, daily_cost, mot_due, tax_due, service_due, status FROM vehicles WHERE company_id = %s", (session.get('company_id'),))
    vehicles = cur.fetchall()
    conn.close()
    return render_template('finance_fleet.html', vehicles=vehicles)

@app.route('/finance/fleet/add', methods=['POST'])
def add_vehicle():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    reg = request.form.get('reg')
    model = request.form.get('model')
    cost = request.form.get('cost') or 0
    mot = request.form.get('mot') or None
    tax = request.form.get('tax') or None
    status = request.form.get('status')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vehicles (company_id, reg_plate, make_model, daily_cost, mot_due, tax_due, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (session.get('company_id'), reg, model, cost, mot, tax, status))
        conn.commit()
        flash("Vehicle Added")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('finance_fleet'))

@app.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM vehicles WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit()
    conn.close()
    return redirect(url_for('finance_fleet'))


# --- MATERIALS ROUTES ---
@app.route('/finance/materials')
def finance_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    # Create Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            sku TEXT,
            name TEXT,
            category TEXT,
            unit TEXT,
            cost_price DECIMAL(10,2),
            supplier TEXT
        );
    """)
    conn.commit()
    
    # Fetch Data
    cur.execute("SELECT id, sku, name, category, unit, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (session.get('company_id'),))
    materials = cur.fetchall()
    conn.close()
    return render_template('finance_materials.html', materials=materials)

@app.route('/finance/materials/add', methods=['POST'])
def add_material():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    supplier = request.form.get('supplier')
    sku = request.form.get('sku')
    name = request.form.get('name')
    cat = request.form.get('category')
    unit = request.form.get('unit')
    cost = request.form.get('cost') or 0
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (session.get('company_id'), sku, name, cat, unit, cost, supplier))
        conn.commit()
        flash("Item Added")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('finance_materials'))

@app.route('/finance/materials/delete/<int:id>')
def delete_material(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM materials WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit()
    conn.close()
    return redirect(url_for('finance_materials'))
    
# --- ANALYSIS ROUTES ---
@app.route('/finance/analysis')
def finance_analysis():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Fetch Completed Jobs (Mocking Job Data based on Transactions for now)
    # Ideally this joins with a real 'Jobs' table, but we will use Transactions as proxy 
    # to show the math working.
    
    # We look for Income transactions that have a Reference
    cur.execute("""
        SELECT reference, description, amount 
        FROM transactions 
        WHERE company_id = %s AND type = 'Income' 
        ORDER BY date DESC LIMIT 50
    """, (comp_id,))
    
    raw_jobs = cur.fetchall()
    
    # Get Markup Setting
    cur.execute("SELECT value FROM settings WHERE key='default_markup' AND company_id=%s", (comp_id,))
    row = cur.fetchone()
    markup_percent = float(row[0]) if row else 20.0
    markup_factor = 1 + (markup_percent / 100)
    
    analyzed_jobs = []
    total_rev = 0
    total_cost = 0
    
    for j in raw_jobs:
        ref = j[0] if j[0] else "UNK"
        desc = j[1]
        rev = float(j[2])
        
        # Reverse Engineer Cost based on Margin
        est_cost = rev / markup_factor
        profit = rev - est_cost
        margin = (profit / rev * 100) if rev > 0 else 0
        
        total_rev += rev
        total_cost += est_cost
        
        analyzed_jobs.append({
            "ref": ref, "client": desc, "status": "Completed",
            "rev": rev, "cost": est_cost, "profit": profit, "margin": margin
        })

    conn.close()
    
    total_profit = total_rev - total_cost
    avg_margin = (total_profit / total_rev * 100) if total_rev > 0 else 0
    
    return render_template('finance_analysis.html', 
                           jobs=analyzed_jobs, 
                           total_rev=total_rev, 
                           total_cost=total_cost, 
                           total_profit=total_profit, 
                           avg_margin=avg_margin)


# --- SETTINGS ROUTES ---
@app.route('/finance/settings')
def finance_settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # Ensure settings table exists (with company_id)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            company_id INTEGER,
            key TEXT,
            value TEXT,
            PRIMARY KEY (company_id, key)
        );
    """)
    conn.commit()
    
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (session.get('company_id'),))
    rows = cur.fetchall()
    conn.close()
    
    # Convert list of rows to dictionary
    settings_dict = {row[0]: row[1] for row in rows}
    
    # Defaults
    brand = settings_dict.get('brand_color', '#27AE60') # Default Green
    ui_mode = settings_dict.get('ui_mode', 'light')
    
    return render_template('finance_settings.html', 
                           settings=settings_dict, 
                           brand_color=brand, 
                           ui_mode=ui_mode)

@app.route('/finance/settings/save', methods=['POST'])
def save_settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    comp_id = session.get('company_id')
    form_data = request.form.to_dict()
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Save every field in the form to the DB
        for key, value in form_data.items():
            # Upsert (Insert or Update)
            cur.execute("""
                INSERT INTO settings (company_id, key, value) 
                VALUES (%s, %s, %s)
                ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value
            """, (comp_id, key, value))
            
        conn.commit()
        flash("Configuration Saved Successfully!")
    except Exception as e:
        conn.rollback()
        flash(f"Error saving settings: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('finance_settings'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)