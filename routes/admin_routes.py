from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db
from werkzeug.security import generate_password_hash
from datetime import datetime
import re
import json
import os
import zipfile

admin_bp = Blueprint('admin', __name__)

# --- HELPER: PERFORM SINGLE BACKUP (Used by Single & Mass Backup) ---
def perform_company_backup(company_id, cur):
    backup_data = {}
    
    # THE COMPLETE LIST OF TABLES
    # We include 'companies' and 'subscriptions' to ensure we capture the core account info
    tables = [
        'companies', 'subscriptions', 'settings',  # Core & Branding
        'users', 'staff',                          # People
        'vehicles', 'materials',                   # Assets
        'clients', 'properties',                   # CRM
        'service_requests', 'transactions'         # Data
    ]
    
    for table in tables:
        # Check if table exists first (Safety check)
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
    cur.execute("SELECT id, username, role, company_id FROM users ORDER BY id ASC")
    users = cur.fetchall()

    # 3. System Settings (For SMTP Config)
    cur.execute("CREATE TABLE IF NOT EXISTS system_settings (key TEXT PRIMARY KEY, value TEXT)") # Safety check
    cur.execute("SELECT key, value FROM system_settings")
    settings_rows = cur.fetchall()
    system_config = {row[0]: row[1] for row in settings_rows}
    
    conn.close()
    
    # Pass all data to the template
    return render_template('super_admin.html', companies=companies, users=users, config=system_config)


# --- 2. HANDLE PASSWORD RESET ---
@admin_bp.route('/admin/reset-password', methods=['POST'])
def reset_user_password():
    if session.get('role') != 'SuperAdmin':
        return "Access Denied", 403
    
    user_id = request.form.get('user_id')
    new_pass = request.form.get('new_password')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        new_hash = generate_password_hash(new_pass)
        cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
        conn.commit()
        flash(f"✅ Password for User ID {user_id} updated successfully.")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error resetting password: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 3. SUSPEND / ACTIVATE COMPANY ---
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


# --- 4. UPDATE TIER (Basic / Pro / Enterprise) ---
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


# --- 5. RUN BACKUP FOR A COMPANY ---
@admin_bp.route('/admin/backup/<int:company_id>')
def backup_company(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        data = perform_company_backup(company_id, cur)
        
        # Save to JSON
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"FULL_BACKUP_Co{company_id}_{timestamp}.json"
        
        # Ensure backup directory exists
        backup_dir = os.path.join(os.getcwd(), 'static', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        filepath = os.path.join(backup_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=4, default=str)
            
        flash(f"💾 Complete Backup (inc. Logo/Fleet) saved: {filename}")
        
    except Exception as e:
        flash(f"❌ Backup Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 6. MASS BACKUP (ALL COMPANIES) ---
@admin_bp.route('/admin/backup/all')
def backup_all_companies():
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Get all Company IDs
        cur.execute("SELECT id FROM companies")
        company_ids = [row[0] for row in cur.fetchall()]
        
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        backup_dir = os.path.join(os.getcwd(), 'static', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # 2. Create a ZIP file to hold all backups
        zip_filename = f"MASS_BACKUP_{timestamp}.zip"
        zip_path = os.path.join(backup_dir, zip_filename)
        
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for c_id in company_ids:
                # Generate data for this company
                data = perform_company_backup(c_id, cur)
                
                # Write individual JSON inside the ZIP
                json_name = f"Company_{c_id}_Data.json"
                zipf.writestr(json_name, json.dumps(data, indent=4, default=str))
        
        flash(f"✅ MASS BACKUP COMPLETE! Saved {len(company_ids)} companies to {zip_filename}")
        
    except Exception as e:
        flash(f"❌ Mass Backup Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))


# --- 7. SYSTEM SETTINGS & SMTP ---
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
    
    # --- 8. DELETE COMPANY (THE NUCLEAR OPTION) ---
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