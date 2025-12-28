from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.utils import secure_filename
import psycopg2
import os

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 

# --- CONFIG FOR LOGO UPLOADS ---
UPLOAD_FOLDER = 'static/uploads/logos'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure the upload folder exists on the server
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

# --- BRANDING HELPER ---
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
        "logo": settings_dict.get('logo_url', '/static/images/logo.png')
    }

# --- MAIN STATIC PAGES ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/about')
def about(): return render_template('about.html')

@app.route('/services')
def services(): return render_template('services.html')

@app.route('/tradecore')
def tradecore(): return render_template('tradecore.html')

@app.route('/forensics')
def forensics(): return render_template('forensics.html')

@app.route('/contact')
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
def login():
    if request.method == 'POST':
        email_or_user = request.form.get('email')
        password = request.form.get('password')
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, username, role, company_id FROM users WHERE (username = %s OR email = %s) AND password_hash = %s", (email_or_user, email_or_user, password))
        user = cur.fetchone()
        conn.close()
        if user:
            session['user_id'], session['user_name'], session['role'], session['company_id'] = user
            return redirect(url_for('super_admin_dashboard') if user[2] == 'SuperAdmin' else url_for('main_launcher'))
        flash('Invalid Email or Password')
    return render_template('login.html')

@app.route('/dashboard-menu')
def main_launcher():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('main_launcher.html', role=session.get('role'))

# --- FINANCE SECTIONS (DASHBOARD, HR, FLEET, MATERIALS, ANALYSIS) ---
@app.route('/finance-dashboard')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (comp_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (comp_id,))
    expense = cur.fetchone()[0] or 0.0
    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (comp_id,))
    transactions = cur.fetchall()
    conn.close()
    return render_template('finance_dashboard.html', total_income=income, total_expense=expense, total_balance=income-expense, transactions=transactions, brand_color=config['color'], logo_url=config['logo'])

@app.route('/finance/hr')
def finance_hr():
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = cur.fetchall(); conn.close()
    return render_template('finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@app.route('/finance/fleet')
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: 
        return redirect(url_for('login'))
        
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db()
    cur = conn.cursor()

    # --- UPDATED: DATABASE AUTO-REPAIR (Added repair_cost) ---
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS tracker_url TEXT;")
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS defect_notes TEXT;")
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS defect_image TEXT;")
    cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS repair_cost DECIMAL(10,2) DEFAULT 0.00;")
    conn.commit()

    # --- UPDATED: PULLING DATA (v[10] is now repair_cost) ---
    cur.execute("""
        SELECT id, reg_plate, make_model, daily_cost, mot_due, tax_due, 
               service_due, status, defect_notes, tracker_url, repair_cost 
        FROM vehicles WHERE company_id = %s
    """, (comp_id,))
    
    vehicles = cur.fetchall()
    conn.close()
    
    return render_template('finance_fleet.html', 
                           vehicles=vehicles, 
                           brand_color=config['color'], 
                           logo_url=config['logo'])

@app.route('/finance/fleet/update_repair', methods=['POST'])
def update_repair():
    if session.get('role') not in ['Admin', 'SuperAdmin']: 
        return redirect(url_for('login'))
        
    vehicle_id = request.form.get('vehicle_id')
    cost = request.form.get('repair_cost') or 0
    notes = request.form.get('defect_notes')
    status = request.form.get('status') # Allows office to move it back to 'Active'
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE vehicles 
            SET repair_cost = %s, defect_notes = %s, status = %s 
            WHERE id = %s AND company_id = %s
        """, (cost, notes, status, vehicle_id, session.get('company_id')))
        conn.commit()
        flash("✅ Vehicle Repair Details Updated")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('finance_fleet'))
    
@app.route('/finance/materials')
def finance_materials():
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, sku, name, category, unit, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (comp_id,))
    materials = cur.fetchall(); conn.close()
    return render_template('finance_materials.html', materials=materials, brand_color=config['color'], logo_url=config['logo'])

# --- SETTINGS & LOGO UPLOAD ---
@app.route('/finance/settings')
def finance_settings():
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall(); conn.close()
    settings_dict = {row[0]: row[1] for row in rows}
    return render_template('finance_settings.html', settings=settings_dict, brand_color=config['color'], logo_url=config['logo'])

@app.route('/finance/settings/save', methods=['POST'])
@app.route('/finance/settings/save', methods=['POST'])
def save_settings():
    comp_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Handle Text Fields (Currency, Tax, Brand Color, etc.)
    for key, value in request.form.items():
        cur.execute("""
            INSERT INTO settings (company_id, key, value) 
            VALUES (%s, %s, %s) 
            ON CONFLICT (company_id, key) 
            DO UPDATE SET value = EXCLUDED.value
        """, (comp_id, key, value))
    
    # 2. Handle Logo Upload (Saving to the 5GB Persistent Disk)
    if 'logo' in request.files:
        file = request.files['logo']
        if file and allowed_file(file.filename):
            # Ensure the sub-folder exists on the disk
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            
            filename = secure_filename(f"logo_{comp_id}_{file.filename}")
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            
            # Save the physical file to the disk
            file.save(file_path)
            
            # Save the WEB PATH to the database so the browser can find it
            # This must match your static folder structure
            db_path = f"/static/uploads/logos/{filename}"
            cur.execute("""
                INSERT INTO settings (company_id, key, value) 
                VALUES (%s, 'logo_url', %s) 
                ON CONFLICT (company_id, key) 
                DO UPDATE SET value = EXCLUDED.value
            """, (comp_id, db_path))

    conn.commit()
    conn.close()
    flash("Configuration Saved Successfully!")
    return redirect(url_for('finance_settings'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)