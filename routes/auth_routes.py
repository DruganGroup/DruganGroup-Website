from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

# --- 1. STAFF & ADMIN LOGIN ---
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, send them to the launcher
    if 'user_id' in session:
        return redirect(url_for('auth.main_launcher'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        # Check users table and join with staff to get real name
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
            # If no staff record is found, it falls back to the username
            session['user_name'] = user[5] if user[5] else user[1] 
            
            return redirect(url_for('auth.main_launcher'))
        else:
            flash("❌ Invalid Staff Credentials")
            
    # Render the login page (ensure this template exists in templates/public/login.html)
    return render_template('public/login.html')

@auth_bp.route('/launcher')
def main_launcher():
    # 1. Security Check
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    # 2. REDIRECT SUPER ADMIN (User ID 1)
    if session.get('user_id') == 1:
        # Set these for the header
        session['user_name'] = "Master Admin"
        session['company_name'] = "Business Better HQ"
        # Send you to the actual admin dashboard route
        return redirect(url_for('admin.super_admin_dashboard'))

    # 3. STAFF LOGIC (Everyone else)
    return render_template('main_launcher.html', role=session.get('role'))

    # 3. STAFF LOGIC (Everyone else)
    return render_template('main_launcher.html', role=session.get('role'))

# --- 3. LOGOUT ---
@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("🔒 You have been logged out securely.")
    return redirect(url_for('auth.login'))