from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db
from werkzeug.security import generate_password_hash
from datetime import datetime
import re


admin_bp = Blueprint('admin', __name__)

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
            # Important: We hash the password here for consistency
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
    
    # 2. Users (NEW: For Password Reset Table)
    cur.execute("SELECT id, username, role, company_id FROM users ORDER BY id ASC")
    users = cur.fetchall()
    
    conn.close()
    
    # Pass both 'companies' and 'users' to the template
    return render_template('super_admin.html', companies=companies, users=users)

# --- NEW ROUTE: HANDLE PASSWORD RESET ---
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
    admin_bp.route('/admin/suspend/<int:company_id>')
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
        new_status = cur.fetchone()[0]
        conn.commit()
        flash(f"✅ Company ID {company_id} is now {new_status}")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))

# --- 2. UPDATE TIER (Basic / Pro / Enterprise) ---
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

# --- 3. RUN BACKUP FOR A COMPANY ---
@admin_bp.route('/admin/backup/<int:company_id>')
def backup_company(company_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied", 403
    
    conn = get_db()
    cur = conn.cursor()
    backup_data = {}
    
    try:
        # Gather all data for this company
        tables = ['users', 'clients', 'properties', 'service_requests', 'transactions', 'staff']
        for table in tables:
            # Check if table exists first to avoid errors
            cur.execute(f"SELECT to_regclass('{table}')")
            if cur.fetchone()[0]:
                cur.execute(f"SELECT * FROM {table} WHERE company_id = %s", (company_id,))
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                # Convert rows to list of dicts
                backup_data[table] = [dict(zip(columns, row)) for row in rows]
        
        # Save to file (simulated secure storage)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"backup_co{company_id}_{timestamp}.json"
        
        # Ensure backup directory exists
        backup_dir = os.path.join(os.getcwd(), 'static', 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        filepath = os.path.join(backup_dir, filename)
        
        # Write JSON (Handle date serialization manually if needed, usually default=str works)
        with open(filepath, 'w') as f:
            json.dump(backup_data, f, indent=4, default=str)
            
        flash(f"💾 Backup successful! Saved to: static/backups/{filename}")
        
    except Exception as e:
        flash(f"❌ Backup Failed: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('admin.super_admin_dashboard'))