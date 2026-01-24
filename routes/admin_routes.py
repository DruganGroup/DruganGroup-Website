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
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, send_from_directory, current_app
from db import get_db, get_site_config
from werkzeug.security import generate_password_hash

admin_bp = Blueprint('admin', __name__)

# --- HELPER: RECORD AUDIT LOG ---
def log_audit(action, target, details=""):
    try:
        conn = get_db()
        cur = conn.cursor()
        email = session.get('user_email', 'Unknown')
        if request.headers.getlist("X-Forwarded-For"):
            ip = request.headers.getlist("X-Forwarded-For")[0]
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
        except:
            # FIX: If a table is missing, rollback so the DB connection stays alive
            cur.connection.rollback()
            
    total_bytes += (row_count * 2048)

    # Check Physical Files
    try:
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'logo_url'", (company_id,))
        row = cur.fetchone()
        if row and row[0]:
            file_path = row[0].replace('/static/', 'static/')
            if os.path.exists(file_path): total_bytes += os.path.getsize(file_path)
    except:
        cur.connection.rollback()

    try:
        cur.execute("SELECT defect_image_url FROM vehicles WHERE company_id = %s", (company_id,))
        for row in cur.fetchall():
            if row[0]:
                file_path = row[0].replace('/static/', 'static/')
                if os.path.exists(file_path): total_bytes += os.path.getsize(file_path)
    except:
        cur.connection.rollback()

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

@admin_bp.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # --- 1. HANDLE FORM SUBMISSION (CREATE COMPANY) ---
    if request.method == 'POST':
        c_name = request.form.get('company_name')
        owner_name = request.form.get('owner_name')
        owner_email = request.form.get('owner_email')
        plan_id = request.form.get('plan_id') 
        
        # Fetch Plan Details
        cur.execute("SELECT name, max_users, max_vehicles, max_clients, max_properties, max_storage, modules FROM plans WHERE id = %s", (plan_id,))
        selected_plan = cur.fetchone()
        
        if selected_plan:
            plan_name, p_users, p_vehicles, p_clients, p_props, p_storage, p_modules = selected_plan
            
            # Generate Subdomain
            import re
            base_slug = re.sub(r'[^a-z0-9-]', '', c_name.lower().replace(' ', '-'))
            final_slug = base_slug
            
            try:
                # Create Company
                cur.execute("INSERT INTO companies (name, contact_email, subdomain) VALUES (%s, %s, %s) RETURNING id", (c_name, owner_email, final_slug))
                new_id = cur.fetchone()[0]
                
                # Create Subscription
                cur.execute("""
                    INSERT INTO subscriptions 
                    (company_id, plan_id, plan_tier, status, start_date, max_users, max_vehicles, max_clients, max_properties, max_storage, modules) 
                    VALUES (%s, %s, %s, 'Active', CURRENT_DATE, %s, %s, %s, %s, %s, %s)
                """, (new_id, plan_id, plan_name, p_users, p_vehicles, p_clients, p_props, p_storage, p_modules))
                
                # Create Owner
                from werkzeug.security import generate_password_hash
                import random, string
                temp_pass = ''.join(random.choices(string.ascii_letters + string.digits, k=10))
                hashed = generate_password_hash(temp_pass)
                
                cur.execute("""
                    INSERT INTO users (company_id, name, email, password_hash, role) 
                    VALUES (%s, %s, %s, %s, 'Admin')
                """, (new_id, owner_name, owner_email, hashed))

                # Create Staff Profile
                cur.execute("""
                    INSERT INTO staff (company_id, name, email, position, status, pay_rate) 
                    VALUES (%s, %s, %s, 'Director', 'Active', 0.00)
                """, (new_id, owner_name, owner_email))

                conn.commit()
                flash(f"✅ Company '{c_name}' created on '{plan_name}' Plan! Password: {temp_pass}")
                
            except Exception as e:
                conn.rollback()
                flash(f"❌ Error: {e}")
        else:
            flash("❌ Error: Selected plan not found.")

    # --- 2. FETCH DATA FOR DASHBOARD ---
    
    # A. Fetch Plans
    cur.execute("SELECT id, name, price FROM plans ORDER BY price ASC")
    rows = cur.fetchall()
    available_plans = [{'id': r[0], 'name': r[1], 'price': r[2]} for r in rows]

    # B. Fetch Companies List (NOW INCLUDES START DATE)
    cur.execute("""
        SELECT c.id, c.name, c.subdomain, s.plan_tier, s.status, u.email, s.start_date
        FROM companies c
        LEFT JOIN subscriptions s ON c.id = s.company_id
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin'
        ORDER BY c.id DESC
    """)
    companies = []
    for row in cur.fetchall():
        # Format the date nicely (e.g. "14 Jan 2026")
        raw_date = row[6]
        formatted_date = raw_date.strftime('%d %b %Y') if raw_date else "Pending"

        companies.append({
            'id': row[0], 
            'name': row[1], 
            'subdomain': row[2], 
            'plan': row[3], 
            'status': row[4], 
            'admin': row[5],
            'joined': formatted_date  # <--- THIS WAS MISSING
        })

    conn.close()
    return render_template('super_admin.html', companies=companies, plans=available_plans)

@admin_bp.route('/super-admin/analytics')
def super_admin_analytics():
    if session.get('role') != 'SuperAdmin': 
        return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # FETCH TABLE INVENTORY & ROW COUNTS
    db_inventory = []
    try:
        cur.execute("""
            SELECT table_name FROM information_schema.tables 
            WHERE table_schema = 'public' ORDER BY table_name;
        """)
        tables = [row[0] for row in cur.fetchall()]
        for t in tables:
            try:
                cur.execute(f"SELECT COUNT(*) FROM {t}")
                db_inventory.append({'name': t, 'rows': cur.fetchone()[0]})
            except:
                cur.connection.rollback()
                db_inventory.append({'name': t, 'rows': 'Error'})
    except: pass

    # FETCH COMPANY STATS
    cur.execute("SELECT id, name FROM companies")
    raw_comps = cur.fetchall()
    analytics_data = []
    existing_table_names = [item['name'] for item in db_inventory]
    
    for comp in raw_comps:
        stat = {'name': comp[1], 'id': comp[0], 'total_rows': 0, 'breakdown': {}}
        for t in ['users', 'staff', 'vehicles', 'clients', 'jobs', 'transactions', 'maintenance_logs']:
            if t in existing_table_names:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (comp[0],))
                    c = cur.fetchone()[0]
                    stat['breakdown'][t] = c
                    stat['total_rows'] += c
                except: cur.connection.rollback()
        
        stat['est_size_mb'] = round((stat['total_rows'] * 0.5) / 1024, 2)
        stat['bandwidth_usage'] = round(stat['total_rows'] * 0.05, 2)
        analytics_data.append(stat)
    
    conn.close()
    return render_template('admin/super_admin_analytics.html', data=analytics_data, db_inventory=db_inventory)

# --- 3. UTILITIES ---
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
            
            log_audit("RESET PASSWORD", user[1], "Admin reset via dashboard")
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
        log_audit("UPDATE SETTINGS", "System Settings", "Updated SMTP/Alert Config")
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
    conn.commit()
    log_audit("TOGGLE SUSPEND", f"Company ID {company_id}", "Changed subscription status")
    conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

# --- ROBUST DELETE COMPANY ---
@admin_bp.route('/admin/delete-tenant/<int:company_id>')
def delete_tenant(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    try:
        # STEP 1: Delete "Grandchildren"
        grandchildren = ['invoice_items', 'quote_items', 'overhead_items', 'vehicle_crews', 'job_logs']
        for t in grandchildren:
            try: cur.execute(f"DELETE FROM {t} USING companies WHERE {t}.company_id = companies.id AND companies.id = %s", (company_id,))
            except Exception: conn.rollback() 

        # STEP 2: Delete "Children"
        children = ['maintenance_logs', 'materials', 'overhead_categories', 'transactions', 'service_requests', 'invoices', 'quotes', 'jobs']
        for t in children:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (company_id,))
            except Exception: conn.rollback()

        # STEP 3: Delete "Direct Dependents"
        dependents = ['vehicles', 'staff', 'properties', 'clients', 'users', 'settings', 'subscriptions']
        for t in dependents:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (company_id,))
            except Exception: conn.rollback()

        # STEP 4: Delete the Company
        cur.execute("DELETE FROM companies WHERE id = %s", (company_id,))
        
        conn.commit()
        log_audit("DELETE COMPANY", f"Company ID {company_id}", "Deleted via Super Admin Dashboard")
        flash("✅ Company and all associated data deleted permanently.")
        
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error deleting company: {e}")
    finally:
        conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

# --- BACKUP SYSTEM: VIEW LIST ---
@admin_bp.route('/admin/backup/all')
def view_backups():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    # Define folder path (matches your existing setup)
    backup_folder = os.path.join(os.getcwd(), 'static', 'backups')
    
    # Ensure folder exists
    if not os.path.exists(backup_folder):
        os.makedirs(backup_folder)

    # Get list of files
    backup_files = []
    try:
        files = os.listdir(backup_folder)
        # Sort by date (newest first)
        files.sort(key=lambda x: os.path.getmtime(os.path.join(backup_folder, x)), reverse=True)
        
        for index, filename in enumerate(files):
            if filename.endswith('.zip'):
                filepath = os.path.join(backup_folder, filename)
                size_mb = os.path.getsize(filepath) / (1024 * 1024)
                created_at = datetime.fromtimestamp(os.path.getmtime(filepath)).strftime('%d-%b-%Y %H:%M')
                
                backup_files.append({
                    'id': index + 1,
                    'filename': filename,
                    'size': f"{size_mb:.2f} MB",
                    'created_at': created_at
                })
    except Exception as e:
        flash(f"Error reading backups: {e}")

    return render_template('admin/backups.html', backups=backup_files)

# --- BACKUP SYSTEM: CREATE NEW ---
@admin_bp.route('/admin/backup/create')
def create_backup():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    try:
        # Get all company IDs
        cur.execute("SELECT id FROM companies")
        ids = [row[0] for row in cur.fetchall()]
        
        # Create Zip File
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        backup_folder = os.path.join(os.getcwd(), 'static', 'backups')
        os.makedirs(backup_folder, exist_ok=True)
        
        filename = f"MASS_BACKUP_{timestamp}.zip"
        zip_path = os.path.join(backup_folder, filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for c_id in ids:
                # Uses your existing helper function 'perform_company_backup'
                data = perform_company_backup(c_id, cur)
                zipf.writestr(f"Company_{c_id}.json", json.dumps(data, indent=4, default=str))
                
        log_audit("CREATE BACKUP", "All Companies", f"Created {filename}")
        flash(f"✅ Success! Snapshot created: {filename}")
        
    except Exception as e:
        flash(f"❌ Backup Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.view_backups'))

# --- BACKUP SYSTEM: DOWNLOAD ---
@admin_bp.route('/admin/backup/download/<filename>')
def download_backup(filename):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    # SECURITY FIX: PREVENT PATH TRAVERSAL
    from werkzeug.utils import secure_filename
    safe_filename = secure_filename(filename)
    
    backup_folder = os.path.join(os.getcwd(), 'static', 'backups')
    return send_from_directory(backup_folder, safe_filename, as_attachment=True)

# --- BACKUP SYSTEM: DELETE ---
@admin_bp.route('/admin/backup/delete/<filename>')
def delete_backup(filename):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    # SECURITY FIX: PREVENT PATH TRAVERSAL
    from werkzeug.utils import secure_filename
    safe_filename = secure_filename(filename)
    
    backup_folder = os.path.join(os.getcwd(), 'static', 'backups')
    filepath = os.path.join(backup_folder, safe_filename)
    
    try:
        # SAFETY CHECK: Ensure file exists before deleting
        if os.path.exists(filepath):
            os.remove(filepath)
            flash(f"🗑️ Deleted archive: {safe_filename}")
            log_audit("DELETE BACKUP", safe_filename, "Deleted manually")
        else:
            flash("❌ File not found.")
    except Exception as e:
        flash(f"Error deleting file: {e}")
        
    return redirect(url_for('admin.view_backups'))

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
    
# --- GLOBAL SEARCH ---
@admin_bp.route('/admin/global-search')
def global_search():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    query = request.args.get('q', '').strip()
    if not query: return redirect(url_for('admin.super_admin_dashboard'))
    conn = get_db(); cur = conn.cursor()
    results = {'companies': [], 'users': [], 'invoices': [], 'vehicles': []}
    try:
        cur.execute("SELECT id, name, subdomain, contact_email FROM companies WHERE name ILIKE %s OR subdomain ILIKE %s", (f'%{query}%', f'%{query}%'))
        results['companies'] = cur.fetchall()
        cur.execute("SELECT u.id, u.email, u.role, c.name, c.id FROM users u LEFT JOIN companies c ON u.company_id = c.id WHERE u.email ILIKE %s OR u.username ILIKE %s", (f'%{query}%', f'%{query}%'))
        results['users'] = cur.fetchall()
        try:
            cur.execute("SELECT i.id, i.invoice_number, i.total, c.name, c.id FROM invoices i LEFT JOIN companies c ON i.company_id = c.id WHERE i.invoice_number ILIKE %s", (f'%{query}%',))
            results['invoices'] = cur.fetchall()
        except: pass
        try:
            cur.execute("SELECT v.id, v.registration, v.make, c.name, c.id FROM vehicles v LEFT JOIN companies c ON v.company_id = c.id WHERE v.registration ILIKE %s", (f'%{query}%',))
            results['vehicles'] = cur.fetchall()
        except: pass
    except Exception as e: print(f"Search Error: {e}")
    finally: conn.close()
    return render_template('admin/search_results.html', query=query, results=results)
    
# --- 4. COMPANY INSPECTION ---
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

    try:
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,)); settings = {row[0]: row[1] for row in cur.fetchall()}
        cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,)); stats['total_revenue'] = cur.fetchone()[0] or 0.0
    except Exception: conn.rollback(); settings = {}; stats['total_revenue'] = 0.0
    
    stats['storage_mb'] = get_real_company_usage(company_id, cur)
    conn.close()
    return render_template('admin/company_details.html', company=company, stats=stats, settings=settings)

# --- 5. DATA CLEANUP (FORENSIC MODE) ---
@admin_bp.route('/admin/cleanup-my-data')
def cleanup_super_admin_data():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    deleted_summary = [] 
    try:
        target_id = session.get('company_id')
        if not target_id: target_id = 1 
        
        # 1. READ BEFORE DELETE
        try:
            cur.execute("SELECT id, first_name, last_name FROM staff WHERE company_id = %s", (target_id,))
            staff_rows = cur.fetchall()
            if staff_rows: deleted_summary.append(f"Staff Removed: {len(staff_rows)}")
        except: pass

        try:
            cur.execute("SELECT id, name FROM clients WHERE company_id = %s", (target_id,))
            client_rows = cur.fetchall()
            if client_rows: deleted_summary.append(f"Clients Removed: {len(client_rows)}")
        except: pass

        try:
            cur.execute("SELECT id, registration FROM vehicles WHERE company_id = %s", (target_id,))
            vehicle_rows = cur.fetchall()
            if vehicle_rows: deleted_summary.append(f"Vehicles Removed: {len(vehicle_rows)}")
        except: pass

        # 2. DELETE ORDER
        grandchildren = ['invoice_items', 'quote_items', 'overhead_items', 'vehicle_crews', 'job_logs']
        for t in grandchildren:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (target_id,))
            except: conn.rollback() 

        children = ['maintenance_logs', 'materials', 'overhead_categories', 'transactions', 'service_requests', 'invoices', 'quotes', 'jobs']
        for t in children:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (target_id,))
            except: conn.rollback()

        parents = ['vehicles', 'staff', 'properties', 'clients']
        for t in parents:
            try: cur.execute(f"DELETE FROM {t} WHERE company_id = %s", (target_id,))
            except: conn.rollback()

        conn.commit()
        
        log_details = " | ".join(deleted_summary) if deleted_summary else "No data found."
        log_audit("WIPE DATA", f"Company ID {target_id}", log_details)
        
        flash(f"✅ Wipe Complete. Checked Audit Log for details.")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))
    
@admin_bp.route('/admin/wipe-fleet-data')
def wipe_fleet_data():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    target_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM maintenance_logs WHERE company_id = %s", (target_id,))
        cur.execute("DELETE FROM vehicle_crews WHERE company_id = %s", (target_id,))
        cur.execute("DELETE FROM vehicles WHERE company_id = %s", (target_id,))
        conn.commit(); flash("✅ Fleet Data Wiped")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))
    
# --- SETUP: CREATE LOG TABLES ---
@admin_bp.route('/admin/setup-logs-db')
def setup_logs_db():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY, admin_email VARCHAR(150), action VARCHAR(100), target VARCHAR(255), details TEXT, ip_address VARCHAR(50), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id SERIAL PRIMARY KEY, level VARCHAR(20) DEFAULT 'ERROR', message TEXT, traceback TEXT, route VARCHAR(100), created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit(); flash("✅ Log Tables Created Successfully")
    except Exception as e: conn.rollback(); flash(f"❌ Error: {e}")
    finally: conn.close()
    return redirect(url_for('admin.super_admin_dashboard'))

@admin_bp.route('/admin/audit-logs')
def view_audit_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get Count
    cur.execute("SELECT COUNT(*) FROM audit_logs")
    total_logs = cur.fetchone()[0]
    total_pages = math.ceil(total_logs / per_page)
    
    # Fetch Logs (Joining Company Name)
    cur.execute("""
        SELECT 
            TO_CHAR(a.created_at, 'DD Mon HH24:MI') as time_str,
            a.admin_email,
            a.action,
            a.target,
            a.details,
            a.ip_address,
            c.name as company_name
        FROM audit_logs a
        LEFT JOIN companies c ON a.company_id = c.id
        ORDER BY a.created_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    logs = cur.fetchall()
    conn.close()
    
    return render_template('admin/audit_logs.html', 
                           logs=logs, 
                           page=page, 
                           total_pages=total_pages)
    
@admin_bp.route('/admin/system-logs')
def view_system_logs():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM system_logs")
    total_logs = cur.fetchone()[0]
    total_pages = math.ceil(total_logs / per_page)
    
    # Fetch Logs with User/Company Joins
    cur.execute("""
        SELECT 
            s.id,
            TO_CHAR(s.created_at, 'DD Mon HH24:MI') as time_str,
            s.level,
            s.message,
            s.traceback,
            s.route,
            s.ip_address,
            u.username,
            c.name as company_name,
            s.status_code
        FROM system_logs s
        LEFT JOIN users u ON s.user_id = u.id
        LEFT JOIN companies c ON s.company_id = c.id
        ORDER BY s.created_at DESC
        LIMIT %s OFFSET %s
    """, (per_page, offset))
    logs = cur.fetchall()
    conn.close()
    
    return render_template('admin/system_logs.html', 
                           logs=logs, 
                           page=page, 
                           total_pages=total_pages)

# =========================================================
# GLOBAL NUCLEAR RESET (Wipes ALL Tenants' Transaction Data)
# =========================================================
@admin_bp.route('/admin/system/global-nuclear-reset')
def global_nuclear_reset():
    # 1. SECURITY CHECK (SuperAdmin Only)
    if session.get('role') != 'SuperAdmin': 
        return "❌ ACCESS DENIED: Only SuperAdmins can press the red button."
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # --- PHASE 1: FINANCE ---
        # Clear Invoicing Data
        cur.execute("DELETE FROM invoice_items")
        cur.execute("DELETE FROM invoices")
        
        # --- PHASE 2: OPERATIONS ---
        # Clear Job Data (Dependencies first)
        cur.execute("DELETE FROM job_materials")
        
        # Clear Compliance/RAMS (Safely check if table exists)
        try: cur.execute("DELETE FROM certificates") 
        except: pass 
        
        # Clear Jobs (This clears the Calendar)
        cur.execute("DELETE FROM jobs")
        
        # --- PHASE 3: SALES & SERVICE ---
        # Clear Quotes
        cur.execute("DELETE FROM quote_items")
        cur.execute("DELETE FROM quotes")
        
        # Clear Service Desk
        cur.execute("DELETE FROM service_requests")

        conn.commit()
        flash("🌍 GLOBAL RESET SUCCESSFUL: All Jobs, Quotes, and Invoices have been wiped system-wide.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"❌ Reset Failed: {e}", "error")
        return f"Error executing reset: {e}"
        
    finally:
        conn.close()

    # Redirect to Dashboard (which should now be empty)
    return redirect(url_for('office.office_dashboard'))
    
@admin_bp.route('/admin/fix-logs-db')
def fix_logs_db():
    if session.get('role') not in ['SuperAdmin', 'Admin']:
        return "Access Denied", 403

    conn = get_db()
    cur = conn.cursor()
    messages = []
    
    # Columns to add to system_logs so the View route works
    commands = [
        "ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS ip_address TEXT;",
        "ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS company_id INTEGER;",
        "ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS user_id INTEGER;",
        "ALTER TABLE system_logs ADD COLUMN IF NOT EXISTS status_code INTEGER DEFAULT 500;"
    ]
    
    try:
        for sql in commands:
            cur.execute(sql)
            messages.append(f"✅ Executed: {sql}")
        
        conn.commit()
        messages.append("SUCCESS: Database upgraded! You can now view System Logs.")
    except Exception as e:
        conn.rollback()
        messages.append(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return "<br>".join(messages)