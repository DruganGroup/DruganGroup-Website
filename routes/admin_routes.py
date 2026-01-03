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

# --- RESTORED HELPER: RECORD AUDIT LOG ---
def log_audit(action, target, details=""):
    try:
        conn = get_db()
        cur = conn.cursor()
        email = session.get('user_email', 'Unknown')
        # Optimized IP detection
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

# --- RESTORED HELPER: CALCULATE REAL DISK USAGE ---
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

# --- RESTORED HELPER: BACKUP LOGIC ---
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

# --- 1. SUPER ADMIN DASHBOARD (PULSE INTEGRATED) ---
@admin_bp.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # PULSE CALCULATIONS
    cur.execute("SELECT COUNT(*) FROM companies")
    total_companies = cur.fetchone()[0]
    cur.execute("SELECT SUM(CASE WHEN plan_tier='Professional' THEN 50 WHEN plan_tier='Enterprise' THEN 150 ELSE 0 END) FROM subscriptions WHERE status='Active'")
    mrr = cur.fetchone()[0] or 0
    
    # --- CREATE NEW COMPANY LOGIC ---
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
            conn.commit()
            flash(f"✅ Created {comp_name}. Temporary Pass: {owner_pass}")
        except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")

    # FETCH COMPANIES
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
    
    # SYSTEM CONFIG & BROADCAST ALERT
    cur.execute("SELECT key, value FROM system_settings WHERE key != 'global_alert'")
    system_config = {row[0]: row[1] for row in cur.fetchall()}
    cur.execute("SELECT value FROM system_settings WHERE key = 'global_alert'")
    alert_row = cur.fetchone()
    global_alert = alert_row[0] if alert_row else ""
    
    conn.close()
    return render_template('super_admin.html', 
                           companies=companies, users=users, 
                           config=system_config, global_alert=global_alert,
                           pulse={'mrr': mrr, 'comps': total_companies, 'rows': 0})

# --- RESTORED: ANALYTICS ---
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

# --- NEW: BROADCAST ROUTE ---
@admin_bp.route('/admin/broadcast', methods=['POST'])
def update_broadcast():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    alert_msg = request.form.get('global_alert', '')
    conn = get_db(); cur = conn.cursor()
    cur.execute("INSERT INTO system_settings (key, value) VALUES ('global_alert', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (alert_msg,))
    conn.commit(); conn.close()
    flash("✅ System Broadcast Updated")
    return redirect(url_for('admin.super_admin_dashboard'))

# --- CLEANED: SMTP SETTINGS ---
@admin_bp.route('/admin/settings', methods=['POST'])
def save_system_settings():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    conn = get_db(); cur = conn.cursor()
    settings = {'smtp_server': request.form.get('smtp_server'), 'smtp_port': request.form.get('smtp_port'), 'smtp_email': request.form.get('smtp_email'), 'smtp_password': request.form.get('smtp_password')}
    for key, val in settings.items():
        cur.execute("INSERT INTO system_settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, val))
    conn.commit(); conn.close()
    flash("✅ SMTP Settings Saved")
    return redirect(url_for('admin.super_admin_dashboard'))

# --- RESTORED: GLOBAL SEARCH ---
@admin_bp.route('/admin/global-search')
def global_search():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    query = request.args.get('q', '').strip()
    conn = get_db(); cur = conn.cursor()
    results = {'companies': [], 'users': [], 'invoices': [], 'vehicles': []}
    try:
        cur.execute("SELECT id, name, subdomain FROM companies WHERE name ILIKE %s OR subdomain ILIKE %s", (f'%{query}%', f'%{query}%'))
        results['companies'] = cur.fetchall()
        cur.execute("SELECT id, email, role FROM users WHERE email ILIKE %s", (f'%{query}%',))
        results['users'] = cur.fetchall()
    except Exception as e: print(f"Search Error: {e}")
    finally: conn.close()
    return render_template('admin/search_results.html', query=query, results=results)

# --- PAGINATED LOGS ---
@admin_bp.route('/admin/logs/audit')
def view_audit_logs():
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * 20
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM audit_logs")
    total = cur.fetchone()[0]
    cur.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 20 OFFSET %s", (offset,))
    logs = cur.fetchall()
    conn.close()
    return render_template('admin/audit_logs.html', logs=logs, page=page, total_pages=(total // 20) + 1)

@admin_bp.route('/admin/logs/system')
def view_system_logs():
    page = request.args.get('page', 1, type=int)
    offset = (page - 1) * 20
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM system_logs")
    total = cur.fetchone()[0]
    cur.execute("SELECT * FROM system_logs ORDER BY id DESC LIMIT 20 OFFSET %s", (offset,))
    logs = cur.fetchall()
    conn.close()
    return render_template('admin/system_logs.html', logs=logs, page=page, total_pages=(total // 20) + 1)

# --- REMAINING UTILITIES PRESERVED ---
@admin_bp.route('/admin/suspend/<int:company_id>')
def toggle_suspend(company_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE subscriptions SET status = CASE WHEN status = 'Active' THEN 'Suspended' ELSE 'Active' END WHERE company_id = %s", (company_id,))
    conn.commit(); conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/delete-tenant/<int:company_id>')
def delete_tenant(company_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
    conn.commit(); conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/assign-me/<int:company_id>')
def assign_super_admin(company_id):
    session['company_id'] = company_id
    return redirect(url_for('auth.main_launcher'))