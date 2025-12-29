from flask import Blueprint, render_template, session, redirect, url_for, flash
from db import get_db, get_site_config
from email_service import send_company_email

office_bp = Blueprint('office', __name__)

# --- THE SECURITY GATEKEEPER ---
# Allowed roles for Office Hub: Admin, SuperAdmin, Office
# 'Site' users are NOT in this list.
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']

@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    # 1. Check if Logged In
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    # 2. Check if Role is Allowed (SECURITY LOCK)
    if session.get('role') not in ALLOWED_OFFICE_ROLES:
        flash("⛔ Access Denied: Office Hub is for management staff only.")
        return redirect(url_for('auth.main_launcher'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get Financial Summaries (Visible to Office Staff)
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    
    # Get Recent Transactions
    cur.execute("SELECT id, date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 10", (company_id,))
    transactions = cur.fetchall()
    conn.close()

    return render_template('office/office_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           transactions=transactions,
                           brand_color=config['color'],
                           logo_url=config['logo'])

@office_bp.route('/office/send-receipt/<int:transaction_id>')
def send_receipt(transaction_id):
    # Security Check
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return redirect(url_for('auth.main_launcher'))
    
    company_id = session.get('company_id')
    user_email = "test_client@example.com" # Placeholder
    
    subject = f"Receipt for Transaction #{transaction_id}"
    body = f"<h2>Transaction Receipt</h2><p>This is a confirmation for transaction #{transaction_id}.</p>"
    
    success, message = send_company_email(company_id, user_email, subject, body)
    
    if success: flash(f"✅ Email sent successfully to {user_email}!")
    else: flash(f"❌ Email Failed: {message}")
        
    return redirect(url_for('office.office_dashboard'))