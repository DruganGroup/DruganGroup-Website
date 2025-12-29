from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
from werkzeug.security import check_password_hash

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        # ... (your POST logic) ...
        pass
    # Updated path to include the 'public' folder
    return render_template('public/login.html', active_tab='staff')

@auth_bp.route('/portal/login', methods=['GET', 'POST'])
def client_portal_login():
    if request.method == 'POST':
        # ... (your POST logic) ...
        pass
    # Updated path to include the 'public' folder
    return render_template('public/login.html', active_tab='client')

@auth_bp.route('/portal/login', methods=['GET', 'POST'])
def client_portal_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        # Look in the CLIENTS table
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
            
    return render_template('auth/login.html', active_tab='client')

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