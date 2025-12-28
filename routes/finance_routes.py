from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from werkzeug.utils import secure_filename
import os
from db import get_db, get_site_config, allowed_file, UPLOAD_FOLDER

finance_bp = Blueprint('finance', __name__)

# --- DASHBOARD OVERVIEW ---
@finance_bp.route('/finance-dashboard')
@finance_bp.route('/finance-dashboard.html')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"

    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()

    # Financial Calcs
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    balance = income - expense

    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (company_id,))
    transactions = cur.fetchall()
    
    conn.close()
    return render_template('finance/finance_dashboard.html', total_income=income, total_expense=expense, total_balance=balance, transactions=transactions, brand_color=config['color'], logo_url=config['logo'])


# --- HR & STAFF ---
@finance_bp.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = cur.fetchall()
    conn.close()
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

@finance_bp.route('/finance/hr/add', methods=['POST'])
def add_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    name = request.form.get('name')
    position = request.form.get('position')
    dept = request.form.get('dept')
    rate = request.form.get('rate') or 0
    model = request.form.get('model')
    access = request.form.get('access_level')
    comp_id = session.get('company_id')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level) VALUES (%s, %s, %s, %s, %s, %s, %s)", (comp_id, name, position, dept, rate, model, access))
        if access != "None":
            username = name.split(" ")[0].lower() + f"{comp_id}"
            email_fake = f"{username}@tradekore.com"
            default_pass = "Password123!" 
            cur.execute("SELECT id FROM users WHERE username=%s", (username,))
            if not cur.fetchone():
                cur.execute("INSERT INTO users (username, email, password_hash, role, company_id) VALUES (%s, %s, %s, %s, %s)", (username, email_fake, default_pass, access, comp_id))
                flash(f"✅ Staff added! Login: {username} / Pass: {default_pass}")
        conn.commit()
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    return redirect(url_for('finance.finance_hr')) # Note 'finance.' prefix


# --- FLEET ---
@finance_bp.route('/finance/fleet')
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, reg_plate, make_model, daily_cost, mot_due, tax_due, service_due, status, defect_notes, tracker_url, repair_cost FROM vehicles WHERE company_id = %s", (comp_id,))
    vehicles = cur.fetchall()
    conn.close()
    return render_template('finance/finance_fleet.html', vehicles=vehicles, brand_color=config['color'], logo_url=config['logo'])


# --- SETTINGS ---
@finance_bp.route('/finance/settings')
def finance_settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall(); conn.close()
    settings_dict = {row[0]: row[1] for row in rows}
    
    return render_template('finance/finance_settings.html', settings=settings_dict, brand_color=config['color'], logo_url=config['logo'])