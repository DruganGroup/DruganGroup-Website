from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from werkzeug.utils import secure_filename
import os
from db import get_db, get_site_config, allowed_file, UPLOAD_FOLDER

finance_bp = Blueprint('finance', __name__)

# 1. OVERVIEW
@finance_bp.route('/finance-dashboard')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"

    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()

    # Ensure Transactions Table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY, company_id INTEGER, date DATE,
            type TEXT, category TEXT, description TEXT, amount DECIMAL(10,2), reference TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

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


# 2. HR & STAFF
@finance_bp.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS staff (id SERIAL PRIMARY KEY, company_id INTEGER, name TEXT, position TEXT, dept TEXT, pay_rate DECIMAL(10,2), pay_model TEXT, access_level TEXT);")
    conn.commit()
    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff = cur.fetchall()
    conn.close()
    return render_template('finance/finance_hr.html', staff=staff, brand_color=config['color'], logo_url=config['logo'])

# 3. FLEET (FIXED TO ADD MISSING COLUMNS)
@finance_bp.route('/finance/fleet')
def finance_fleet():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Ensure Table Exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id SERIAL PRIMARY KEY, company_id INTEGER, reg_plate TEXT, make_model TEXT, 
            daily_cost DECIMAL(10,2), mot_due DATE, tax_due DATE, service_due DATE, 
            status TEXT, tracker_url TEXT, defect_notes TEXT, defect_image TEXT, 
            repair_cost DECIMAL(10,2) DEFAULT 0.00
        );
    """)
    conn.commit()
    @finance_bp.route('/finance/fleet/add', methods=['POST'])
def add_vehicle():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    
    # Get form data
    reg = request.form.get('reg')
    model = request.form.get('model')
    cost = request.form.get('cost') or 0
    mot = request.form.get('mot') or None
    tax = request.form.get('tax') or None
    status = request.form.get('status')
    tracker = request.form.get('tracker_url')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vehicles 
            (company_id, reg_plate, make_model, daily_cost, mot_due, tax_due, status, tracker_url) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, reg, model, cost, mot, tax, status, tracker))
        conn.commit()
        flash("Vehicle Added Successfully")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('finance.finance_fleet'))

@finance_bp.route('/finance/fleet/delete/<int:id>')
def delete_vehicle(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM vehicles WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error deleting vehicle: {e}")
    finally:
        conn.close()
    return redirect(url_for('finance.finance_fleet'))

    # 2. FIX MISSING COLUMNS (Run this safely)
    try:
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS tracker_url TEXT;")
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS defect_notes TEXT;")
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS defect_image TEXT;")
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS repair_cost DECIMAL(10,2) DEFAULT 0.00;")
        conn.commit()
    except Exception as e:
        print(f"Column update skipped or failed: {e}")
        conn.rollback()

    # 3. Select Data
    cur.execute("SELECT id, reg_plate, make_model, daily_cost, mot_due, tax_due, service_due, status, defect_notes, tracker_url, repair_cost FROM vehicles WHERE company_id = %s", (comp_id,))
    vehicles = cur.fetchall()
    conn.close()
    
    return render_template('finance/finance_fleet.html', vehicles=vehicles, brand_color=config['color'], logo_url=config['logo'])


# 4. MATERIALS
@finance_bp.route('/finance/materials')
def finance_materials():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS materials (id SERIAL PRIMARY KEY, company_id INTEGER, sku TEXT, name TEXT, category TEXT, unit TEXT, cost_price DECIMAL(10,2), supplier TEXT);")
    conn.commit()
    cur.execute("SELECT id, sku, name, category, unit, cost_price, supplier FROM materials WHERE company_id = %s ORDER BY name", (comp_id,))
    materials = cur.fetchall()
    conn.close()
    return render_template('finance/finance_materials.html', materials=materials, brand_color=config['color'], logo_url=config['logo'])

# 5. SETTINGS
@finance_bp.route('/finance/settings')
def finance_settings():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS settings (company_id INTEGER, key TEXT, value TEXT, PRIMARY KEY (company_id, key));")
    conn.commit()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall(); conn.close()
    settings_dict = {row[0]: row[1] for row in rows}
    return render_template('finance/finance_settings.html', settings=settings_dict, brand_color=config['color'], logo_url=config['logo'])