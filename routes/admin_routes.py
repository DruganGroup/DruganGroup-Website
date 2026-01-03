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

# --- HELPER: RECORD AUDIT LOG ---
def log_audit(action, target, details=""):
    try:
        conn = get_db()
        cur = conn.cursor()
        email = session.get('user_email', 'Unknown')
        
        # FIX: Get only the user's actual IP from the access route
        if request.access_route:
            ip = request.access_route[0]
        else:
            ip = request.remote_addr
            
        cur.execute("""
            INSERT INTO audit_logs (admin_email, action, target, details, ip_address)
            VALUES (%s, %s, %s, %s, %s)
        """, (email, action, target, details, ip))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Logging Failed: {e}") 

# --- HELPER: CALCULATE REAL DISK USAGE ---
def get_real_company_usage(company_id, cur):
    total_bytes = 0
    tables = ['users', 'staff', 'vehicles', 'clients', 'jobs', 'transactions', 'maintenance_logs', 'materials']
    row_count = 0
    for t in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (company_id,))
            row_count += cur.fetchone()[0]
        except: pass
    total_bytes += (row_count * 2048)

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

# --- 1. SUPER ADMIN DASHBOARD ---
@admin_bp.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        plan = request.form.get('plan')
        
        chars = string.ascii_letters + string.digits + "!@#$%"
        owner_pass = ''.join(random.choice(chars) for i in range(12))

        base_slug = re.sub(r'[^a-z0-9-]', '', comp_name.lower().replace(' ', '-'))
        final_slug = base_slug; counter = 1
        while True:
            cur.execute("SELECT id FROM companies WHERE subdomain = %s", (final_slug,))
            if not cur.fetchone(): break 
            final_slug = f"{base_slug}-{counter}"; counter += 1

        try:
            cur.execute("INSERT INTO companies (name, contact_email, subdomain) VALUES (%s, %s, %s) RETURNING id", (comp_name, owner_email, final_slug))
            new_id = cur.fetchone()[0]
            cur.execute("INSERT INTO subscriptions (company_id, plan_tier, status, start_date) VALUES (%s, %s, 'Active', CURRENT_DATE)", (new_id, plan))
            secure_pass = generate_password_hash(owner_pass)
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, 'Admin', %s)", (owner_email, secure_pass, owner_email, new_id))
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'brand_color', '#2c3e50')", (new_id,))
            
            cur.execute("SELECT key, value FROM system_settings")
            sys_conf = {row[0]: row[1] for row in cur.fetchall()}
            
            if sys_conf.get('smtp_server') and sys_conf.get('smtp_email'):
                try:
                    msg = MIMEMultipart()
                    msg['From'] = sys_conf['smtp_email']; msg['To'] = owner_email; msg['Subject'] = f"Welcome to Business Better"
                    body = f"Login URL: https://www.drugangroup.co.uk/login\nUser: {owner_email}\nPass: {owner_pass}"
                    msg.attach(MIMEText(body, 'plain'))
                    server = smtplib.SMTP(sys_conf['smtp_server'], int(sys_conf.get('smtp_port', 587)))
                    server.starttls(); server.login(sys_conf['smtp_email'], sys_conf['smtp_password'])
                    server.send_message(msg); server.quit()
                    conn.commit(); log_audit("CREATE COMPANY", comp_name)
                    flash(f"✅ Success! Created {comp_name}.")
                except Exception as e:
                    conn.commit(); flash(f"⚠️ Created, but email failed. Pass: {owner_pass}")
            else:
                conn.commit(); flash(f"⚠️ Created. Pass: {owner_pass}")
        except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")

    cur.execute("""
        SELECT c.id, c.name, c.subdomain, s.plan_tier, s.status, s.start_date, u.email
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
        real_size_mb = get_real_company_usage(c[0], cur)
        companies.append({
            'id': c[0], 'name': c[1], 'subdomain': c[2],
            'plan': c[3] if c[3] else 'Basic', 'status': c[4] if c[4] else 'Active', 
            'email': c[6] if c[6] else 'No Admin', 'created': created_date,
            'storage': real_size_mb
        })
    
    cur.execute("SELECT id, username, role, company_id FROM users WHERE role IN ('SuperAdmin', 'Admin') ORDER BY id ASC")
    users = cur.fetchall()
    
    # FETCH SYSTEM SETTINGS (Separating Alert)
    cur.execute("SELECT key, value FROM system_settings WHERE key != 'global_alert'")
    system_config = {row[0]: row[1] for row in cur.fetchall()}
    cur.execute("SELECT value FROM system_settings WHERE key = 'global_alert'")
    alert_row = cur.fetchone()
    global_alert = alert_row[0] if alert_row else ""
    
    conn.close()
    return render_template('super_admin.html', companies=companies, users=users, config=system_config, global_alert=global_alert)

# --- 2. SEPARATED ALERT SYSTEM ---
@admin_bp.route('/admin/broadcast', methods=['POST'])
def update_broadcast():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    alert_msg = request.form.get('global_alert', '')
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO system_settings (key, value) VALUES ('global_alert', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (alert_msg,))
    conn.commit(); conn.close()
    log_audit("UPDATE BROADCAST", "System", f"Alert: {alert_msg}")
    flash("✅ System Broadcast Updated")
    return redirect(url_for('admin.super_admin_dashboard'))

# --- 3. ANALYTICS ---
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

# --- 4. SMTP SETTINGS (CLEANED) ---
@admin_bp.route('/admin/settings', methods=['POST'])
def save_system_settings():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    conn = get_db(); cur = conn.cursor()
    settings = {
        'smtp_server': request.form.get('smtp_server'),
        'smtp_port': request.form.get('smtp_port'),
        'smtp_email': request.form.get('smtp_email'),
        'smtp_password': request.form.get('smtp_password')
    }
    try:
        for key, val in settings.items():
            cur.execute("INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, val))
        conn.commit(); flash("✅ SMTP Settings Saved")
        log_audit("UPDATE SMTP", "System Settings")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

# --- 5. LOGS (PAGINATED) ---
@admin_bp.route('/admin/logs/audit')
def view_audit_logs():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM audit_logs")
    total_logs = cur.fetchone()[0]
    total_pages = (total_logs // per_page) + (1 if total_logs % per_page > 0 else 0)
    cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
    logs = cur.fetchall()
    conn.close()
    return render_template('admin/audit_logs.html', logs=logs, page=page, total_pages=total_pages)

@admin_bp.route('/admin/logs/system')
def view_system_logs():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM system_logs")
    total_logs = cur.fetchone()[0]
    total_pages = (total_logs // per_page) + (1 if total_logs % per_page > 0 else 0)
    cur.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT %s OFFSET %s", (per_page, offset))
    logs = cur.fetchall()
    conn.close()
    return render_template('admin/system_logs.html', logs=logs, page=page, total_pages=total_pages)

# --- 6. TENANT MANAGEMENT ---
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
            conn.commit(); log_audit("RESET PASSWORD", user[1])
            flash(f"✅ Reset to: {secure_pass}")
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
    cur.execute("UPDATE users SET company_id = NULL WHERE id = %s", (session.get('user_id'),))
    session['company_id'] = None
    conn.commit(); conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/suspend/<int:company_id>')
def toggle_suspend(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE subscriptions SET status = CASE WHEN status = 'Active' THEN 'Suspended' ELSE 'Active' END WHERE company_id = %s", (company_id,))
    conn.commit(); conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/delete-tenant/<int:company_id>')
def delete_tenant(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        tables = ['invoice_items', 'quote_items', 'overhead_items', 'vehicle_crews', 'job_logs', 'maintenance_logs', 'materials', 'overhead_categories', 'transactions', 'service_requests', 'invoices', 'quotes', 'jobs', 'vehicles', 'staff', 'properties', 'clients', 'users', 'settings', 'subscriptions']
        for t in tables:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (company_id,))
            except: conn.rollback()
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        conn.commit(); log_audit("DELETE COMPANY", f"ID {company_id}")
        flash("✅ Deleted permanently.")
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
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

# --- 7. COMPANY INSPECTION ---
@admin_bp.route('/super-admin/company/<int:company_id>')
def company_details(company_id):
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT c.id, c.name, c.subdomain, c.contact_email, s.plan_tier, s.status, s.start_date FROM companies c LEFT JOIN subscriptions s ON c.id = s.company_id WHERE c.id = %s", (company_id,))
    comp = cur.fetchone()
    if not comp: conn.close(); return "Company not found", 404
    company = {'id': comp[0], 'name': comp[1], 'subdomain': comp[2], 'email': comp[3], 'plan': comp[4], 'status': comp[5], 'joined': comp[6]}
    tables = ['users', 'staff', 'clients', 'vehicles', 'properties', 'jobs', 'quotes', 'invoices', 'transactions', 'service_requests']
    stats = {}
    for t in tables:
        try: cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (company_id,)); stats[t] = cur.fetchone()[0]
        except Exception: conn.rollback(); stats[t] = 0
    stats['storage_mb'] = get_real_company_usage(company_id, cur)
    conn.close()
    return render_template('admin/company_details.html', company=company, stats=stats)

@admin_bp.route('/admin/cleanup-my-data')
def cleanup_super_admin_data():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        target_id = session.get('company_id', 1)
        tables = ['invoice_items', 'quote_items', 'overhead_items', 'vehicle_crews', 'job_logs', 'maintenance_logs', 'materials', 'overhead_categories', 'transactions', 'service_requests', 'invoices', 'quotes', 'jobs', 'vehicles', 'staff', 'properties', 'clients']
        for t in tables:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (target_id,))
            except: conn.rollback()
        conn.commit(); log_audit("WIPE DATA", f"ID {target_id}")
        flash(f"✅ Wipe Complete.")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))