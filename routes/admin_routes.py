import os
import re
import json
import zipfile
import random
import string
import smtplib
from datetime import datetime, date, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db
from werkzeug.security import generate_password_hash

admin_bp = Blueprint('admin', __name__)

# --- HELPER: CALCULATE REAL DISK USAGE ---
def get_real_company_usage(company_id, cur):
    total_bytes = 0
    # 1. Estimate DB Text Data (2KB per row)
    tables = ['users', 'staff', 'vehicles', 'clients', 'jobs', 'transactions', 'maintenance_logs', 'materials']
    row_count = 0
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (company_id,))
            row_count += cur.fetchone()[0]
        except: pass
    total_bytes += (row_count * 2048)

    # 2. Check Physical Files (Logo & Defect Photos)
    try:
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'logo_url'", (company_id,))
        row = cur.fetchone()
        if row and row[0]:
            file_path = row[0].replace('/static/', 'static/')
            if os.path.exists(file_path): total_bytes += os.path.getsize(file_path)
    except: pass

    try:
        cur.execute("SELECT defect_image_url FROM vehicles WHERE company_id = %s", (company_id,))
        for row in cur.fetchall():
            if row[0]:
                file_path = row[0].replace('/static/', 'static/')
                if os.path.exists(file_path): total_bytes += os.path.getsize(file_path)
    except: pass

    return round(total_bytes / (1024 * 1024), 2)

# --- HELPER: BACKUP LOGIC ---
def perform_company_backup(company_id, cur):
    backup_data = {}
    tables = ['companies', 'subscriptions', 'settings', 'users', 'staff', 'vehicles', 'materials', 'clients', 'properties', 'service_requests', 'transactions', 'maintenance_logs']
    for table in tables:
        try:
            cur.execute(f"SELECT to_regclass('{table}')")
            if cur.fetchone()[0]:
                if table == 'companies': cur.execute(f"SELECT * FROM {table} WHERE id = %s", (company_id,))
                else: cur.execute(f"SELECT * FROM {table} WHERE company_id = %s", (company_id,))
                if cur.description:
                    columns = [desc[0] for desc in cur.description]
                    backup_data[table] = [dict(zip(columns, row)) for row in cur.fetchall()]
        except: pass
    return backup_data

# --- 1. SUPER ADMIN DASHBOARD (Auto-Email & Dates) ---
@admin_bp.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # --- CREATE NEW COMPANY ---
    if request.method == 'POST':
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        plan = request.form.get('plan')
        
        # 1. GENERATE RANDOM PASSWORD
        chars = string.ascii_letters + string.digits + "!@#$%"
        owner_pass = ''.join(random.choice(chars) for i in range(12))

        # 2. Slug Generation
        base_slug = re.sub(r'[^a-z0-9-]', '', comp_name.lower().replace(' ', '-'))
        final_slug = base_slug; counter = 1
        while True:
            cur.execute("SELECT id FROM companies WHERE subdomain = %s", (final_slug,))
            if not cur.fetchone(): break 
            final_slug = f"{base_slug}-{counter}"; counter += 1

        try:
            # 3. Insert Data
            cur.execute("INSERT INTO companies (name, contact_email, subdomain) VALUES (%s, %s, %s) RETURNING id", (comp_name, owner_email, final_slug))
            new_id = cur.fetchone()[0]
            
            cur.execute("INSERT INTO subscriptions (company_id, plan_tier, status, start_date) VALUES (%s, %s, 'Active', CURRENT_DATE)", (new_id, plan))
            
            secure_pass = generate_password_hash(owner_pass)
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, 'Admin', %s)", (owner_email, secure_pass, owner_email, new_id))
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'brand_color', '#2c3e50')", (new_id,))
            
            # 4. FETCH SMTP SETTINGS
            cur.execute("SELECT key, value FROM system_settings")
            sys_conf = {row[0]: row[1] for row in cur.fetchall()}
            
            # 5. SEND WELCOME EMAIL
            if sys_conf.get('smtp_server') and sys_conf.get('smtp_email'):
                try:
                    msg = MIMEMultipart()
                    msg['From'] = sys_conf['smtp_email']
                    msg['To'] = owner_email
                    msg['Subject'] = f"Welcome to TradeCore - {comp_name} Setup Complete"
                    
                    body = f"""
                    Welcome to TradeCore!
                    
                    Your environment has been successfully deployed.
                    
                    DETAILS:
                    --------------------------------------------------
                    Company:   {comp_name}
                    Plan:      {plan}
                    Login URL: https://www.drugangroup.co.uk/login
                    --------------------------------------------------
                    
                    CREDENTIALS:
                    Username:  {owner_email}
                    Password:  {owner_pass}
                    
                    Please login immediately and change your password.
                    """
                    msg.attach(MIMEText(body, 'plain'))
                    
                    server = smtplib.SMTP(sys_conf['smtp_server'], int(sys_conf.get('smtp_port', 587)))
                    server.starttls()
                    server.login(sys_conf['smtp_email'], sys_conf['smtp_password'])
                    server.send_message(msg)
                    server.quit()
                    
                    conn.commit()
                    flash(f"✅ Success! {comp_name} created. Credentials emailed to {owner_email}.")
                except Exception as e:
                    conn.commit()
                    flash(f"⚠️ Account created, but Email Failed: {e}. Password is: {owner_pass}")
            else:
                conn.commit()
                flash(f"⚠️ Account created, but SMTP not configured. Password is: {owner_pass}")

        except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
            
    # --- FETCH DATA WITH DATES ---
    cur.execute("""
        SELECT 
            c.id, c.name, c.subdomain,
            s.plan_tier, s.status, s.start_date,
            u.email
        FROM companies c
        LEFT JOIN subscriptions s ON c.id = s.company_id
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin'
        ORDER BY c.id DESC
    """)
    raw_companies = cur.fetchall()
    
    companies = []
    today = date.today()

    for c in raw_companies:
        created_date = c[5] if c[5] else today
        next_bill = "Unknown"
        
        if created_date:
            try:
                # Billing Logic
                if today.day > created_date.day:
                    month = today.month + 1 if today.month < 12 else 1
                    year = today.year if today.month < 12 else today.year + 1
                    next_bill = date(year, month, created_date.day)
                else:
                    next_bill = date(today.year, today.month, created_date.day)
            except:
                next_bill = created_date + timedelta(days=30)

        real_size_mb = get_real_company_usage(c[0], cur)
        est_bandwidth = round(real_size_mb * 5, 2)
        
        companies.append({
            'id': c[0], 'name': c[1], 'subdomain': c[2],
            'plan': c[3] if c[3] else 'Basic', 
            'status': c[4] if c[4] else 'Active', 
            'email': c[6] if c[6] else 'No Admin',
            'created': created_date,
            'next_bill': next_bill,
            'storage': real_size_mb, 
            'bandwidth': est_bandwidth
        })
    
    cur.execute("SELECT id, username, role, company_id FROM users WHERE role IN ('SuperAdmin', 'Admin') ORDER BY id ASC")
    users = cur.fetchall()
    
    cur.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)") 
    conn.commit()
    cur.execute("SELECT key, value FROM system_settings")
    system_config = {row[0]: row[1] for row in cur.fetchall()}
    
    conn.close()
    return render_template('super_admin.html', companies=companies, users=users, config=system_config)

# --- 2. ANALYTICS ---
@admin_bp.route('/super-admin/analytics')
def super_admin_analytics():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name FROM companies")
    raw_comps = cur.fetchall()
    analytics_data = []
    
    for comp in raw_comps:
        stat = {'name': comp[1], 'id': comp[0], 'total_rows': 0, 'breakdown': {}}
        for t in ['users', 'staff', 'vehicles', 'clients', 'jobs', 'transactions', 'maintenance_logs']:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (comp[0],))
                c = cur.fetchone()[0]
                stat['breakdown'][t] = c; stat['total_rows'] += c
            except: pass
        stat['est_size_mb'] = round((stat['total_rows'] * 0.5) / 1024, 2)
        stat['bandwidth_usage'] = round(stat['total_rows'] * 0.05, 2)
        analytics_data.append(stat)
    
    conn.close()
    return render_template('admin/super_admin_analytics.html', data=analytics_data)

# --- 3. UTILITIES (Password, Settings, Backup) ---
@admin_bp.route('/admin/reset-password', methods=['POST'])
def reset_user_password():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    user_id = request.form.get('user_id')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT username, email FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if user:
            chars = string.ascii_letters + string.digits + "!@#$%"
            secure_pass = ''.join(random.choice(chars) for i in range(12))
            new_hash = generate_password_hash(secure_pass)
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
            
            # Email Logic
            cur.execute("SELECT key, value FROM system_settings")
            settings = {row[0]: row[1] for row in cur.fetchall()}
            if settings.get('smtp_server') and settings.get('smtp_email'):
                msg = MIMEMultipart()
                msg['From'] = settings['smtp_email']; msg['To'] = user[1]; msg['Subject'] = "Password Reset"
                msg.attach(MIMEText(f"Hello {user[0]},\n\nYour new password is: {secure_pass}", 'plain'))
                server = smtplib.SMTP(settings['smtp_server'], int(settings.get('smtp_port', 587)))
                server.starttls(); server.login(settings['smtp_email'], settings['smtp_password'])
                server.send_message(msg); server.quit()
                flash(f"✅ Password emailed to {user[1]}")
            else:
                flash(f"⚠️ Password reset to: {secure_pass} (SMTP Not Configured)")
            conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/settings', methods=['POST'])
def save_system_settings():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    conn = get_db(); cur = conn.cursor()
    settings = {
        'smtp_server': request.form.get('smtp_server'),
        'smtp_port': request.form.get('smtp_port'),
        'smtp_email': request.form.get('smtp_email'),
        'smtp_password': request.form.get('smtp_password'),
        'global_alert': request.form.get('global_alert')
    }
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
        for key, val in settings.items():
            cur.execute("INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, val))
        conn.commit(); flash("✅ Settings Saved")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/assign-me/<int:company_id>')
def assign_super_admin(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET company_id = %s WHERE id = %s", (company_id, session.get('user_id')))
    session['company_id'] = company_id
    conn.commit(); conn.close()
    return redirect(url_for('auth.main_launcher'))

@admin_bp.route('/admin/reset-me')
def reset_super_admin():
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET company_id = 0 WHERE id = %s", (session.get('user_id'),))
    session['company_id'] = 0
    conn.commit(); conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/suspend/<int:company_id>')
def toggle_suspend(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE subscriptions SET status = CASE WHEN status = 'Active' THEN 'Suspended' ELSE 'Active' END WHERE company_id = %s", (company_id,))
    conn.commit(); conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

# --- ROBUST DELETE COMPANY ---
@admin_bp.route('/admin/delete-tenant/<int:company_id>')
def delete_tenant(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        # 1. Manually delete children first to prevent Foreign Key errors
        tables = ['jobs', 'quotes', 'invoices', 'staff', 'vehicles', 'clients', 'properties', 'service_requests', 'transactions', 'maintenance_logs', 'settings', 'subscriptions', 'users']
        for t in tables:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (company_id,))
            except: pass # Ignore if table doesn't exist
            
        # 2. Finally delete the company
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        conn.commit()
        flash("✅ Company and all associated data deleted permanently.")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error deleting company: {e}")
    finally:
        conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/backup/all')
def backup_all_companies():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM companies")
        ids = [row[0] for row in cur.fetchall()]
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        zip_path = os.path.join(os.getcwd(), 'static', 'backups', f"MASS_BACKUP_{timestamp}.zip")
        os.makedirs(os.path.dirname(zip_path), exist_ok=True)
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for c_id in ids:
                data = perform_company_backup(c_id, cur)
                zipf.writestr(f"Company_{c_id}.json", json.dumps(data, indent=4, default=str))
        flash(f"✅ Backup Complete")
    except Exception as e: flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/setup-fleet-db')
def setup_fleet_db():
    conn = get_db(); cur = conn.cursor()
    try:
        cols = ["tax_due DATE", "insurance_due DATE", "service_due DATE", "tracker_url TEXT", "defect_notes TEXT", "defect_image_url TEXT"]
        for c in cols:
            try: cur.execute(f"ALTER TABLE vehicles ADD COLUMN {c};")
            except: pass
        cur.execute("CREATE TABLE IF NOT EXISTS maintenance_logs (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, vehicle_id INTEGER NOT NULL, date DATE DEFAULT CURRENT_DATE, type VARCHAR(50), description TEXT, cost DECIMAL(10,2) DEFAULT 0.00, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);")
        conn.commit(); flash("✅ Fleet DB Upgraded")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/setup-overheads-db')
def setup_overheads_db():
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("CREATE TABLE IF NOT EXISTS overhead_categories (id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL);")
        cur.execute("CREATE TABLE IF NOT EXISTS overhead_items (id SERIAL PRIMARY KEY, category_id INTEGER NOT NULL, name VARCHAR(100) NOT NULL, amount DECIMAL(10,2) DEFAULT 0.00, frequency VARCHAR(20) DEFAULT 'Monthly', FOREIGN KEY (category_id) REFERENCES overhead_categories(id) ON DELETE CASCADE);")
        conn.commit(); flash("✅ Finance DB Upgraded")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))
    
# --- 4. COMPANY INSPECTION (Drill Down) ---
@admin_bp.route('/super-admin/company/<int:company_id>')
def company_details(company_id):
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Basic Info & Plan
    cur.execute("""
        SELECT c.id, c.name, c.subdomain, c.contact_email, s.plan_tier, s.status, s.start_date
        FROM companies c 
        LEFT JOIN subscriptions s ON c.id = s.company_id 
        WHERE c.id = %s
    """, (company_id,))
    comp = cur.fetchone()
    
    if not comp: 
        conn.close()
        return "Company not found", 404
    
    company = {
        'id': comp[0], 'name': comp[1], 'subdomain': comp[2], 'email': comp[3],
        'plan': comp[4], 'status': comp[5], 'joined': comp[6]
    }
    
    # 2. Fetch The "Vital Signs" (Row Counts)
    tables = ['users', 'staff', 'clients', 'vehicles', 'properties', 'jobs', 'quotes', 'invoices', 'transactions', 'service_requests']
    stats = {}
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (company_id,))
            stats[t] = cur.fetchone()[0]
        except Exception:
            # THE FIX: If a query fails (e.g. table doesn't exist), we MUST rollback 
            # the transaction so the connection is clean for the next query.
            conn.rollback() 
            stats[t] = 0

    # 3. Fetch Configuration (Setup)
    # This was crashing before because the transaction was broken above.
    try:
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
    except Exception:
        conn.rollback()
        settings = {}

    # 4. Fetch Financial Summary (Admin Eyes Only)
    try:
        cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
        stats['total_revenue'] = cur.fetchone()[0] or 0.0
    except Exception:
        conn.rollback()
        stats['total_revenue'] = 0.0
    
    # 5. Get Real Disk Usage
    stats['storage_mb'] = get_real_company_usage(company_id, cur)

    conn.close()
    
    return render_template('admin/company_details.html', company=company, stats=stats, settings=settings)
    
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Basic Info & Plan
    cur.execute("""
        SELECT c.id, c.name, c.subdomain, c.contact_email, s.plan_tier, s.status, s.start_date
        FROM companies c 
        LEFT JOIN subscriptions s ON c.id = s.company_id 
        WHERE c.id = %s
    """, (company_id,))
    comp = cur.fetchone()
    
    if not comp: return "Company not found", 404
    
    company = {
        'id': comp[0], 'name': comp[1], 'subdomain': comp[2], 'email': comp[3],
        'plan': comp[4], 'status': comp[5], 'joined': comp[6]
    }
    
    # 2. Fetch The "Vital Signs" (Row Counts)
    tables = ['users', 'staff', 'clients', 'vehicles', 'properties', 'jobs', 'quotes', 'invoices', 'transactions', 'service_requests']
    stats = {}
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (company_id,))
            stats[t] = cur.fetchone()[0]
        except: stats[t] = 0

    # 3. Fetch Configuration (Setup)
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}

    # 4. Fetch Financial Summary (Admin Eyes Only)
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    stats['total_revenue'] = cur.fetchone()[0] or 0.0
    
    # 5. Get Real Disk Usage
    stats['storage_mb'] = get_real_company_usage(company_id, cur)

    conn.close()
    
    return render_template('admin/company_details.html', company=company, stats=stats, settings=settings)

# --- 5. NUKE SUPER ADMIN JUNK DATA ---
@admin_bp.route('/admin/cleanup-my-data')
def cleanup_super_admin_data():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    target_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        tables = ['jobs', 'quotes', 'invoices', 'quote_items', 'invoice_items', 
                  'staff', 'vehicles', 'vehicle_crews', 'maintenance_logs', 
                  'clients', 'properties', 'service_requests', 'transactions', 'materials']
        for t in tables:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (target_id,))
            except: pass
        conn.commit()
        flash("✅ Your testing data has been wiped.")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))