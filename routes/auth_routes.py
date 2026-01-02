from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
# Ensure all security tools are imported
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT u.id, u.username, u.password_hash, u.role, u.company_id, s.name 
            FROM users u 
            LEFT JOIN staff s ON LOWER(TRIM(u.email)) = LOWER(TRIM(s.email)) 
            WHERE LOWER(TRIM(u.username)) = LOWER(TRIM(%s))
        """, (email,))
        
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['role'] = user[3]
            session['company_id'] = user[4]
            
            # STORE THE REAL NAME (User[5] is the name from the staff table)
            # If no staff record is found, it falls back to the email
            session['user_name'] = user[5] if user[5] else user[1] 
            
            return redirect(url_for('auth.main_launcher'))
        else:
            flash("❌ Invalid Staff Credentials")
            
    return render_template('public/login.html', active_tab='staff')
    
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
    
    return render_template('public/login', active_tab='client')

@auth_bp.route('/launcher')
def main_launcher():
    # 1. Security Check
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    return render_template('main_launcher.html', role=session.get('role'))
    
    # --- SUPER ADMIN LOGIC (User ID 1) ---
    if session.get('user_id') == 1:
        conn = get_db()
        cur = conn.cursor()
        
        # 1. Fetch Companies (Fixes the blank screen)
        cur.execute("SELECT id, name, subdomain FROM companies ORDER BY id ASC")
        companies = cur.fetchall()
        
        # 2. Fetch Users (So you can reset their passwords)
        cur.execute("SELECT id, username, role, company_id FROM users ORDER BY id ASC")
        users = cur.fetchall()
        
        conn.close()
        
        # Pass both lists to the template
        return render_template('super_admin.html', companies=companies, users=users)

    # --- STAFF LOGIC (Everyone else) ---
    return render_template('main_launcher.html', role=session.get('role'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("🔒 You have been logged out securely.")
    return redirect(url_for('auth.login'))