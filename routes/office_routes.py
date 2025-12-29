from flask import Blueprint, render_template, session, redirect, url_for, flash
from db import get_db, get_site_config
from email_service import send_company_email

office_bp = Blueprint('office', __name__)

# Allowed roles for Office Hub: Admin, SuperAdmin, Office
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office']

@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    if session.get('role') not in ALLOWED_OFFICE_ROLES:
        flash("⛔ Access Denied: Office Hub is for management staff only.")
        return redirect(url_for('auth.main_launcher'))
    
    company_id = session.get('company_id')
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get Financial Summaries
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

@office_bp.route('/office/service-desk')
def service_desk():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if session.get('role') not in ALLOWED_OFFICE_ROLES:
        flash("⛔ Access Denied")
        return redirect(url_for('auth.main_launcher'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Fetch all Service Requests with Property and Client details
    cur.execute("""
        SELECT 
            r.id, 
            p.address, 
            r.issue_description, 
            c.name as client_name, 
            r.severity, 
            r.status, 
            r.created_at
        FROM service_requests r
        JOIN properties p ON r.property_id = p.id
        JOIN clients c ON r.client_id = c.id
        WHERE r.company_id = %s
        ORDER BY 
            CASE 
                WHEN r.severity = 'Emergency' THEN 1
                WHEN r.severity = 'Urgent' THEN 2
                WHEN r.severity = 'Priority' THEN 3
                WHEN r.severity = 'Scheduled' THEN 4
                ELSE 5
            END, 
            r.created_at DESC
    """, (comp_id,))
    
    rows = cur.fetchall()
    requests_list = []
    for r in rows:
        requests_list.append({
            'id': r[0],
            'property_address': r[1],
            'issue_description': r[2],
            'client_name': r[3],
            'severity': r[4],
            'status': r[5],
            'date': r[6]
        })
        
    conn.close()
    
    return render_template('office/service_desk.html', 
                           requests=requests_list, 
                           brand_color=config['color'], 
                           logo_url=config['logo'])

@office_bp.route('/office/send-receipt/<int:transaction_id>')
def send_receipt(transaction_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return redirect(url_for('auth.main_launcher'))
    
    company_id = session.get('company_id')
    user_email = "test_client@example.com" 
    
    subject = f"Receipt for Transaction #{transaction_id}"
    body = f"<h2>Transaction Receipt</h2><p>This is a confirmation for transaction #{transaction_id}.</p>"
    
    success, message = send_company_email(company_id, user_email, subject, body)
    
    if success: flash(f"✅ Email sent successfully to {user_email}!")
    else: flash(f"❌ Email Failed: {message}")
        
    return redirect(url_for('office.office_dashboard'))