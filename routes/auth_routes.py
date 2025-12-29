from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
@auth_bp.route('/login.html', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email_or_user = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        if not conn: 
            flash("System Error: Database Connection Failed")
            return render_template('public/login.html')
            
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, username, role, company_id 
                FROM users 
                WHERE (username = %s OR email = %s) AND password_hash = %s
            """, (email_or_user, email_or_user, password))
            user = cur.fetchone()
        except Exception as e:
            print(f"Query Error: {e}")
            user = None
        finally:
            conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[2]
            session['company_id'] = user[3]
            
            if user[2] == 'SuperAdmin':
                return redirect(url_for('admin.super_admin_dashboard'))
            else:
                return redirect(url_for('auth.main_launcher'))
        else:
            flash('Invalid Email or Password')

    return render_template('public/login.html')

@auth_bp.route('/dashboard-menu')
@auth_bp.route('/dashboard-menu.html')
def main_launcher():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    return render_template('main_launcher.html', role=session.get('role'))

@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))
    
    from werkzeug.security import check_password_hash

@auth_bp.route('/portal/login', methods=['GET', 'POST'])
def client_portal_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        
        # Check the CLIENTS table
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
            
    # If they just 'land' here via URL, show the login page with the Client tab active
    return render_template('auth/login.html', active_tab='client')