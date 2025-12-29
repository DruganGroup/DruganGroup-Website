from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        # Look in the USERS table for Staff
        cur.execute("SELECT id, username, password_hash, role, company_id FROM users WHERE username = %s", (email,))
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            session['company_id'] = user[4]
            return redirect(url_for('auth.main_launcher'))
        else:
            flash("❌ Invalid Staff Credentials")
            
    # Pointing to templates/public/login.html
    return render_template('public/login.html', active_tab='staff')

@auth_bp.route('/portal/login', methods=['GET', 'POST'])
def client_portal_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        # Look in the CLIENTS table for Customers
        cur.execute("SELECT id, name, company_id, password_hash FROM clients WHERE email = %s", (email,))
        client = cur.fetchone()
        conn.close()
        
        if client and check_password_hash(client[3], password):
            session['client_id'] = client[0]
            session['client_name'] = client[1]
            session['company_id'] = client[2]
            session['role'] = 'Client'
            return redirect(url_for('client.client_portal_home'))
        else:
            flash("❌ Invalid Client Email or Password")
    
    # Pointing to templates/public/login.html
    return render_template('public/login.html', active_tab='client')

@auth_bp.route('/launcher')
def main_launcher():
    if 'user_id' not in session:
        return redirect(url_for('auth.login'))
    return render_template('auth/launcher.html', role=session.get('role'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("🔒 You have been logged out securely.")
    return redirect(url_for('auth.login'))
    from werkzeug.security import generate_password_hash

# --- DIAGNOSTIC & FIX TOOL (DELETE AFTER USE) ---
@auth_bp.route('/debug-auth-fix')
def debug_auth_fix():
    conn = get_db()
    if not conn:
        return "<h1>❌ CRITICAL: Database Connection Failed. Check Render Environment Variables.</h1>"

    cur = conn.cursor()
    target_email = 'admin@drugangroup.co.uk' # CHANGE THIS IF YOUR EMAIL IS DIFFERENT
    target_pass = 'admin123'                 # THIS WILL BE YOUR NEW PASSWORD
    
    # 1. Check if user exists
    cur.execute("SELECT id, username, password_hash FROM users WHERE username = %s", (target_email,))
    user = cur.fetchone()
    
    if not user:
        conn.close()
        return f"<h1>❌ Connected, but User '{target_email}' Not Found</h1><p>Check the spelling of the email in your database.</p>"

    # 2. Show what is currently stored (Safe first few chars)
    current_stored = user[2]
    
    # 3. Force Update to the correct Hash
    new_hash = generate_password_hash(target_pass)
    try:
        cur.execute("UPDATE users SET password_hash = %s WHERE username = %s", (new_hash, target_email))
        conn.commit()
        msg = f"""
        <h1>✅ REPAIR SUCCESSFUL</h1>
        <p><strong>Database Connection:</strong> 100% Active</p>
        <p><strong>User Found:</strong> Yes (ID: {user[0]})</p>
        <p><strong>Previous Password Data:</strong> {current_stored[:15]}...</p>
        <p><strong>Action Taken:</strong> Password reset to secure hash.</p>
        <hr>
        <h3>👉 <a href='/login'>Go Login Now</a></h3>
        <p><strong>Username:</strong> {target_email}</p>
        <p><strong>Password:</strong> {target_pass}</p>
        """
    except Exception as e:
        msg = f"<h1>❌ Update Failed</h1><p>Error: {e}</p>"
    
    conn.close()
    return msg