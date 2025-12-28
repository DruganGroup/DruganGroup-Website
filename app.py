from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import psycopg2
import os

app = Flask(__name__)
# Secure secret key
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 

# --- CONFIG FOR LOGO UPLOADS (Persistent Disk) ---
UPLOAD_FOLDER = 'static/uploads/logos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists on the server disk
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- DATABASE CONNECTION ---
DB_URL = os.environ.get("DATABASE_URL")

def get_db():
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

# --- BRANDING HELPER (Injected into all Finance routes) ---
def get_site_config(comp_id):
    if not comp_id:
        return {"color": "#27AE60", "logo": "/static/images/logo.png"}
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall()
    conn.close()
    settings_dict = {row[0]: row[1] for row in rows}
    return {
        "color": settings_dict.get('brand_color', '#27AE60'),
        "logo": settings_dict.get('logo_url', '/static/images/logo.png'),
        "ui_mode": settings_dict.get('ui_mode', 'light')
    }

# --- MAIN STATIC PAGES (Clean Route + .html Safety Net) ---
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
@app.route('/roofing')
@app.route('/roofing.html')
def roofing(): return render_template('roofing.html')

@app.route('/construction')
@app.route('/construction.html')
def construction(): return render_template('construction.html')

@app.route('/groundworks')
@app.route('/groundworks.html')
def groundworks(): return render_template('groundworks.html')

@app.route('/landscaping')
@app.route('/landscaping.html')
def landscaping(): return render_template('landscaping.html')

@app.route('/maintenance')
@app.route('/maintenance.html')
def maintenance(): return render_template('maintenance.html')

@app.route('/management')
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
            user = None
        finally:
            conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[2]
            session['company_id'] = user[3]
            return redirect(url_for('super_admin_dashboard') if user[2] == 'SuperAdmin' else url_for('main_launcher'))
        else:
            flash('Invalid Email or Password')
    return render_template('login.html')

@app.route('/dashboard-menu')
def main_launcher():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('main_launcher.html', role=session.get('role'))

# --- FINANCE DASHBOARD ---
@app.route('/finance-dashboard')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS transactions (id SERIAL PRIMARY KEY, company_id INTEGER, date DATE, type TEXT, category TEXT, description TEXT, amount DECIMAL(10,2), reference TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
    conn.commit()
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (comp_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (comp_id,))
    expense = cur.fetchone()[0] or 0.0
    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (comp_id,))
    transactions = cur.fetchall()
    cur.execute("SELECT name FROM companies WHERE id = %s", (comp_id,))
    comp_row = cur.fetchone()
    session['company_name'] = comp_row[0] if comp_row else "My Company"
    conn.close()
    return render_template('finance_dashboard.html', total_income=income, total_expense=expense, total_balance=income-expense, transactions=transactions, brand_color=config['color'], logo_url=config['logo'])

# --- HR & STAFF ---
@app.route('/finance/hr')
def finance_hr():
    if 'user_id' not in session: return redirect(url_for('login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id SERIAL PRIMARY KEY, company_id INTEGER, name TEXT, position TEXT, dept TEXT, pay_rate DECIMAL(10,2), pay_model TEXT, access_level TEXT);")
    conn.commit()
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = cur.fetchall(); conn.close()
    return render_template('finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@app.route('/finance/hr/add', methods=['POST'])
def add_staff():
    name = request.form.get('name')
    position = request.form.get('position')
    dept = request.form.get('dept')
    rate = request.form.get('rate') or 0
    model = request.form.get('model')
    access = request.form.get('access_level')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level) VALUES (%s, %s, %s, %s, %s, %s, %s)", (comp_id, name, position, dept, rate, model, access))
        if access != "None":
            username = name.split(" ")[0].lower() + f"{comp_id}"
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", (username, "Password123!", f"{username}@tradekore.com", access, comp_id))
        conn.commit(); flash("✅ Staff added.")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance_hr'))

@app.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance_hr'))

# --- FLEET ---
@app.route('/finance/fleet')
def finance_fleet():
    if 'user_id' not in session: return redirect(url_for('login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS tracker_url TEXT;")
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS defect_notes TEXT;")
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS repair_cost DECIMAL(10,2) DEFAULT 0.00;")
    conn.commit()
    cur.execute("SELECT id, reg_plate, make_model, daily_cost, mot_due, tax_due, service_due, status, defect_notes, tracker_url, repair_cost FROM vehicles WHERE company_id = %s", (comp_id,))
    vehicles = cur.fetchall(); conn.close()
    return render_template('finance_fleet.html', vehicles=vehicles, brand_color=config['color'], logo_url=config['logo'])

@app.route('/finance/fleet/add', methods=['POST'])
def add_vehicle():
    comp_id = session.get('company_id')
    reg = request.form.get('reg'); model = request.form.get('model'); cost = request.form.get('cost') or 0
    mot = request.form.get('mot') or None; tax = request.form.get('tax') or None; status = request.form.get('status')
    tracker = request.form.get('tracker_url')
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO vehicles (company_id, reg_plate, make_model, daily_cost, mot_due, tax_due, status, tracker_url) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)", (comp_id, reg, model, cost, mot, tax, status, tracker))
    conn.commit(); conn.close()
    return redirect(url_for('finance_fleet'))

@app.route('/finance/fleet/update_repair', methods=['POST'])
def update_repair():
    v_id = request.form.get('vehicle_id')
    cost = request.form.get('repair_cost') or 0
    notes = request.form.get('defect_notes')
    status = request.form.get('status')
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE vehicles SET repair_cost = %s, defect_notes = %s, status = %s WHERE id = %s AND company_id = %s", (cost, notes, status, v_id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('finance_fleet'))

# --- MATERIALS ---
@app.route('/finance/materials')
def finance_materials():
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, sku, name, category, unit, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (comp_id,))
    materials = cur.fetchall(); conn.close()
    return render_template('finance_materials.html', materials=materials, brand_color=config['color'], logo_url=config['logo'])

@app.route('/finance/materials/add', methods=['POST'])
def add_material():
    supplier, sku, name, cat, unit, cost = request.form.get('supplier'), request.form.get('sku'), request.form.get('name'), request.form.get('category'), request.form.get('unit'), request.form.get('cost') or 0
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO materials (company_id, sku, name, category, unit, cost_price, supplier) VALUES (%s, %s, %s, %s, %s, %s, %s)", (session.get('company_id'), sku, name, cat, unit, cost, supplier))
    conn.commit(); conn.close()
    return redirect(url_for('finance_materials'))

# --- ANALYSIS ---
@app.route('/finance/analysis')
def finance_analysis():
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT reference, description, amount FROM transactions WHERE company_id = %s AND type = 'Income' ORDER BY date DESC LIMIT 50", (comp_id,))
    raw_jobs = cur.fetchall()
    cur.execute("SELECT value FROM settings WHERE key='default_markup' AND company_id=%s", (comp_id,))
    row = cur.fetchone(); markup_percent = float(row[0]) if row else 20.0
    markup_factor = 1 + (markup_percent / 100)
    analyzed_jobs = []; total_rev = 0; total_cost = 0
    for j in raw_jobs:
        rev = float(j[2]); est_cost = rev / markup_factor; profit = rev - est_cost
        total_rev += rev; total_cost += est_cost
        analyzed_jobs.append({"ref": j[0] or "UNK", "client": j[1], "status": "Completed", "rev": rev, "cost": est_cost, "profit": profit, "margin": (profit/rev*100) if rev>0 else 0})
    conn.close()
    return render_template('finance_analysis.html', jobs=analyzed_jobs, total_rev=total_rev, total_cost=total_cost, total_profit=total_rev-total_cost, avg_margin=(total_rev-total_cost)/total_rev*100 if total_rev>0 else 0, brand_color=config['color'], logo_url=config['logo'])

# --- SETTINGS ---
@app.route('/finance/settings')
def finance_settings():
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall(); conn.close()
    settings_dict = {row[0]: row[1] for row in rows}
    return render_template('finance_settings.html', settings=settings_dict, brand_color=config['color'], logo_url=config['logo'], ui_mode=config['ui_mode'])

@app.route('/finance/settings/save', methods=['POST'])
def save_settings():
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    for key, value in request.form.items():
        cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, key, value))
    if 'logo' in request.files:
        file = request.files['logo']
        if file and allowed_file(file.filename):
            filename = secure_filename(f"logo_{comp_id}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)
            db_path = f"/static/uploads/logos/{filename}"
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'logo_url', %s) ON CONFLICT (company_id, key) DO UPDATE SET value = EXCLUDED.value", (comp_id, db_path))
    conn.commit(); conn.close()
    flash("Configuration Saved Successfully!")
    return redirect(url_for('finance_settings'))

# --- SUPER ADMIN ---
@app.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT c.id, c.name, s.plan_tier, s.status, u.email FROM companies c LEFT JOIN subscriptions s ON c.id = s.company_id LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin' ORDER BY c.id DESC")
    companies = cur.fetchall(); conn.close()
    return render_template('super_admin.html', companies=companies)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)