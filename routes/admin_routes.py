from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db
from werkzeug.security import generate_password_hash
from datetime import datetime
import re
import json
import os
import zipfile
import random
import string
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

admin_bp = Blueprint('admin', __name__)

# --- HELPER: PERFORM SINGLE BACKUP (Used by Single & Mass Backup) ---
def perform_company_backup(company_id, cur):
    backup_data = {}
    
    # THE COMPLETE LIST OF TABLES
    tables = [
        'companies', 'subscriptions', 'settings',  # Core & Branding
        'users', 'staff',                          # People
        'vehicles', 'materials',                   # Assets
        'clients', 'properties',                   # CRM
        'service_requests', 'transactions',        # Data
        'maintenance_logs', 'overhead_categories', 'overhead_items' # NEW TABLES
    ]
    
    for table in tables:
        # Check if table exists first (Safety check)
        try:
            cur.execute(f"SELECT to_regclass('{table}')")
            if cur.fetchone()[0]:
                # Fetch data strictly for this company
                if table == 'companies':
                    cur.execute(f"SELECT * FROM {table} WHERE id = %s", (company_id,))
                else:
                    cur.execute(f"SELECT * FROM {table} WHERE company_id = %s", (company_id,))
                
                if cur.description:
                    columns = [desc[0] for desc in cur.description]
                    rows = cur.fetchall()
                    # Convert rows to list of dicts
                    backup_data[table] = [dict(zip(columns, row)) for row in rows]
        except:
            pass # Skip table if error

    return backup_data


# --- 1. SUPER ADMIN DASHBOARD ---
@admin_bp.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    # Security Check
    if session.get('role') != 'SuperAdmin': 
        return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # --- EXISTING COMPANY CREATION LOGIC ---
    if request.method == 'POST':
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        owner_pass = request.form.get('owner_pass')
        plan = request.form.get('plan')
        
        # 1. Create base slug
        base_slug = re.sub(r'[^a-z0-9-]', '', comp_name.lower().replace(' ', '-'))
        base_slug = re.sub(r'-+', '-', base_slug).strip('-')
        
        # 2. Check for duplicates
        final_slug = base_slug
        counter = 1
        while True:
            cur.execute("SELECT id FROM companies WHERE subdomain = %s", (final_slug,))
            if not cur.fetchone():
                break 
            final_slug = f"{base_slug}-{counter}"
            counter += 1

        try:
            # Create Company
            cur.execute("""
                INSERT INTO companies (name, contact_email, subdomain) 
                VALUES (%s, %s, %s) RETURNING id
            """, (comp_name, owner_email, final_slug))
            new_company_id = cur.fetchone()[0]
            
            # Create Subscription
            cur.execute("INSERT INTO subscriptions (company_id, plan_tier, status) VALUES (%s, %s, 'Active')", (new_company_id, plan))
            
            # Create Admin User
            secure_pass = generate_password_hash(owner_pass)
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, 'Admin', %s)", 
                        (owner_email, secure_pass, owner_email, new_company_id))
            
            # Initialize Default Brand Color
            cur.execute("INSERT INTO settings (company_id, key, value) VALUES (%s, 'brand_color', '#2c3e50')", (new_company_id,))
            
            conn.commit()
            flash(f"✅ Success! {comp_name} created at: {final_slug}.drugangroup.co.uk")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    # --- FETCH DATA FOR DASHBOARD ---
    
    # 1. Companies (Existing)
    cur.execute("""
        SELECT c.id, c.name, s.plan_tier, s.status, u.email, c.subdomain 
        FROM companies c 
        LEFT JOIN subscriptions s ON c.id = s.company_id 
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin' 
        ORDER BY c.id DESC
    """)
    companies = cur.fetchall()
    
    # 2. Users (For Password Reset Table)
    cur.execute("SELECT id, username, role, company_id FROM users WHERE role IN ('SuperAdmin', 'Admin') ORDER BY id ASC")
    users = cur.fetchall()

    # 3. System Settings (For SMTP Config)
    cur.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)") # Safety check
    cur.execute("SELECT key, value FROM system_settings")
    settings_rows = cur.fetchall()
    system_config = {row[0]: row[1] for row in settings_rows}
    
    conn.close()
    
    # Pass all data to the template
    return render_template('admin/super_admin_overview.html', companies=companies, users=users, config=system_config)


# --- 2. ANALYTICS (The Data Probe) ---
@admin_bp.route('/super-admin/analytics')
def super_admin_analytics():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM companies")
    companies = cur.fetchall()
    
    analytics_data = []
    tables_to_check = ['users', 'staff', 'vehicles', 'clients', 'jobs', 'transactions', 'maintenance_logs']
    
    for comp in companies:
        c_id = comp[0]
        c_name = comp[1]
        stat = {'name': c_name, 'total_rows': 0, 'breakdown': {}}
        
        for table in tables_to_check:
            try:
                cur.execute(f"SELECT to_regclass('{table}')")
                if cur.fetchone()[0]:
                    cur.execute(f"SELECT COUNT(*) FROM {table} WHERE company_id = %s", (c_id,))
                    count = cur.fetchone()[0]
                    stat['breakdown'][table] = count
                    stat['total_rows'] += count
            except: pass
        
        stat['est_size_mb'] = round((stat['total_rows'] * 0.5) / 1024, 2)
        stat['bandwidth_usage'] = round(stat['total_rows'] * 0.05, 2)
        analytics_data.append(stat)
    
    analytics_data.sort(key=lambda x: x['total_rows'], reverse=True)
    conn.close()
    return render_template('admin/super_admin_analytics.html', data=analytics_data)


# --- 3. SECURE PASSWORD RESET (GENERATED & EMAILED) ---
@admin_bp.route('/admin/reset-password', methods=['POST'])
def reset_user_password():
    if session.get('role') != 'SuperAdmin':
        return "Access Denied", 403
    
    user_id = request.form.get('user_id')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Get User Details
        cur.execute("SELECT username, email FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        if not user:
            flash("❌ User not found.")
            return redirect(url_for('admin.super_admin_dashboard'))
            
        username = user[0]
        user_email = user[1] # We send the email here

        # 2. Generate a Secure Random Password (12 Chars)
        chars = string.ascii_letters + string.digits + "!@#$%"
        secure_pass = ''.join(random.choice(chars) for i in range(12))
        
        # 3. Update Database (Hash it)
        new_hash = generate_password_hash(secure_pass)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
        
        # 4. Fetch System SMTP Settings
        cur.execute("SELECT key, value FROM system_settings")
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        # 5. Send Email (Only if SMTP is configured)
        if settings.get('smtp_server') and settings.get('smtp_email'):
            msg = MIMEMultipart()
            msg['From'] = settings['smtp_email']
            msg['To'] = user_email
            msg['Subject'] = "Security Alert: Password Reset"
            
            body = f"""
            Hello {username},
            
            Your password has been reset by the System Administrator.
            
            Your new Temporary Password is: {secure_pass}
            
            Please login and change this password immediately.
            
            Regards,
            System Admin
            """
            msg.attach(MIMEText(body, 'plain'))
            
            # Connect to SMTP Server
            server = smtplib.SMTP(settings['smtp_server'], int(settings.get('smtp_port', 587)))
            server.starttls()
            server.login(settings['smtp_email'], settings['smtp_password'])
            server.send_message(msg)
            server.quit()
            
            flash(f"✅ Secure password generated and EMAILED to {user_email}.")
        else:
            # Fallback if no email server is set up yet
            flash(f"⚠️ Password reset to: {secure_pass} (SMTP not configured, so we showed it here).")

        conn.commit()

    except Exception as e:
        conn.rollback()
        flash(f"❌ Error resetting password: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 4. SUSPEND / ACTIVATE COMPANY ---
@admin_bp.route('/admin/suspend/<int:company_id>')
def toggle_suspend(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Toggle between 'Active' and 'Suspended'
        cur.execute("""
            UPDATE subscriptions 
            SET status = CASE WHEN status = 'Active' THEN 'Suspended' ELSE 'Active' END 
            WHERE company_id = %s RETURNING status
        """, (company_id,))
        result = cur.fetchone()
        
        if result:
            new_status = result[0]
            conn.commit()
            flash(f"✅ Company ID {company_id} is now {new_status}")
        else:
            flash("❌ Company subscription not found.")
            
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 5. UPDATE TIER (Basic / Pro / Enterprise) ---
@admin_bp.route('/admin/update-tier', methods=['POST'])
def update_tier():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    company_id = request.form.get('company_id')
    new_tier = request.form.get('plan_tier')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE subscriptions SET plan_tier = %s WHERE company_id = %s", (new_tier, company_id))
        conn.commit()
        flash(f"✅ Company ID {company_id} upgraded to {new_tier}")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 6. RUN BACKUP FOR A COMPANY (NAMED FILE) ---
@admin_bp.route('/admin/backup/<int:company_id>')
def backup_company(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Get Company Name for the filename
        cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
        res = cur.fetchone()
        company_name = res[0] if res else f"Company{company_id}"
        
        # Sanitize name
        safe_name = re.sub(r'[^a-zA-Z0-9]', '_', company_name)
        
        # 2. Perform Backup
        data = perform_company_backup(company_id, cur)
        
        # 3. Save to JSON with CLEAR Name
        timestamp = datetime.now().strftime("%Y-%m-%d")
        filename = f"FULL_BACKUP_{safe_name}_{timestamp}.json"
        
        backup_dir = os.path.join(os.getcwd(), 'static', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        filepath = os.path.join(backup_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4, default=str)
            
        flash(f"💾 Backup Saved: {filename}")
        
    except Exception as e:
        flash(f"❌ Backup Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 7. MASS BACKUP (ALL COMPANIES) ---
@admin_bp.route('/admin/backup/all')
def backup_all_companies():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT id FROM companies")
        company_ids = [row[0] for row in cur.fetchall()]
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        backup_dir = os.path.join(os.getcwd(), 'static', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        zip_filename = f"MASS_BACKUP_{timestamp}.zip"
        zip_path = os.path.join(backup_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for c_id in company_ids:
                data = perform_company_backup(c_id, cur)
                json_name = f"Company_{c_id}_Data.json"
                zipf.writestr(json_name, json.dumps(data, indent=4, default=str))
        
        flash(f"✅ MASS BACKUP COMPLETE! Saved {len(company_ids)} companies to {zip_filename}")
        
    except Exception as e:
        flash(f"❌ Mass Backup Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 8. SYSTEM SETTINGS & SMTP ---
@admin_bp.route('/admin/settings', methods=['POST'])
def save_system_settings():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    # We will store settings as Key-Value pairs in a new table
    settings = {
        'smtp_server': request.form.get('smtp_server'),
        'smtp_port': request.form.get('smtp_port'),
        'smtp_email': request.form.get('smtp_email'),
        'smtp_password': request.form.get('smtp_password'), # In production, encrypt this!
        'global_alert': request.form.get('global_alert')    # For broadcast messages
    }
    
    try:
        # Create table if it doesn't exist
        cur.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)")
        
        for key, val in settings.items():
            cur.execute("""
                INSERT INTO system_settings (key, value) 
                VALUES (%s, %s) 
                ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """, (key, val))
            
        conn.commit()
        flash("✅ System Configuration Saved")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 9. DELETE COMPANY (THE NUCLEAR OPTION) ---
@admin_bp.route('/admin/delete-tenant/<int:company_id>')
def delete_tenant(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Clean up all tables linked to this company
        tables = [
            'transactions', 'service_requests', 'properties', 'clients', 
            'vehicles', 'materials', 'staff', 'users', 
            'system_settings', 'settings', 'subscriptions'
        ]
        
        for table in tables:
            cur.execute(f"SELECT to_regclass('{table}')")
            if cur.fetchone()[0]: 
                cur.execute(f"DELETE FROM {table} WHERE company_id = %s", (company_id,))
        
        # 2. Delete the Company record itself
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        
        conn.commit()
        flash(f"✅ Company ID {company_id} and ALL data have been permanently deleted.")
        
    except Exception as e:
        conn.rollback()
        flash(f"❌ Delete Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))

# --- 10. IMPERSONATION (God Mode) ---
@admin_bp.route('/admin/assign-me/<int:company_id>')
def assign_super_admin(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    user_id = session.get('user_id')
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET company_id = %s WHERE id = %s", (company_id, user_id))
    session['company_id'] = company_id
    conn.commit(); conn.close()
    flash(f"👻 Now viewing as Company ID {company_id}")
    return redirect(url_for('auth.main_launcher'))

@admin_bp.route('/admin/reset-me')
def reset_super_admin():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    user_id = session.get('user_id')
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE users SET company_id = 0 WHERE id = %s", (user_id,))
    session['company_id'] = 0
    conn.commit(); conn.close()
    flash("🛡️ Returned to Super Admin Mode")
    return redirect(url_for('admin.super_admin_dashboard'))

# --- 11. SETUP RECURRING COSTS (Fixed Overheads) ---
@admin_bp.route('/admin/setup-overheads-db')
def setup_overheads_db():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS overhead_categories (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS overhead_items (
                id SERIAL PRIMARY KEY, category_id INTEGER NOT NULL,
                name VARCHAR(100) NOT NULL, amount DECIMAL(10,2) DEFAULT 0.00,
                frequency VARCHAR(20) DEFAULT 'Monthly',
                FOREIGN KEY (category_id) REFERENCES overhead_categories(id) ON DELETE CASCADE
            );
        """)
        conn.commit()
        return "<h1>✅ Overheads DB Ready!</h1><p>You can now track monthly running costs.</p><a href='/finance/settings/overheads'>Go to Settings</a>"
    except Exception as e:
        conn.rollback(); return f"<h1>❌ Database Error</h1><p>{e}</p>"
    finally: conn.close()

# --- 12. SETUP FLEET DB (Fixed Logic) ---
@admin_bp.route('/admin/setup-fleet-db')
def setup_fleet_db():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Add columns
        cols = ["tax_due DATE", "insurance_due DATE", "service_due DATE", "tracker_url TEXT", "defect_notes TEXT", "defect_image_url TEXT"]
        for c in cols:
            try: cur.execute(f"ALTER TABLE vehicles ADD COLUMN {c};")
            except: pass # Ignore if exists
        
        # Create Maintenance Table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS maintenance_logs (
                id SERIAL PRIMARY KEY, company_id INTEGER NOT NULL,
                vehicle_id INTEGER NOT NULL, date DATE DEFAULT CURRENT_DATE,
                type VARCHAR(50), description TEXT, cost DECIMAL(10,2) DEFAULT 0.00,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
        return "<h1>✅ Fleet Database Upgraded!</h1><p>Added Tax, Insurance, Tracker, and Maintenance Logs.</p><a href='/finance/fleet'>Go to Fleet Dashboard</a>"
    except Exception as e:
        conn.rollback(); return f"<h1>❌ Database Error</h1><p>{e}</p>"
    finally: conn.close()