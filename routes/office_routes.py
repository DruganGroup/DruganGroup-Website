from flask import Blueprint, render_template, session, redirect, url_for, flash
from db import get_db, get_site_config
# IMPORT THE NEW EMAIL ENGINE
from email_service import send_company_email

office_bp = Blueprint('office', __name__)

@office_bp.route('/office-hub')
@office_bp.route('/office-hub.html')
def office_dashboard():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    
    # 1. GET BRANDING CONFIG
    config = get_site_config(company_id)
    
    conn = get_db()
    cur = conn.cursor()
    
    # Get Financials
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    
    # Get Recent Jobs (Transactions)
    # We select ID too so we can use it for the email button
    cur.execute("SELECT id, date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 10", (company_id,))
    transactions = cur.fetchall()
    conn.close()

    # Renders the template with BRANDING DATA passed in
    return render_template('office/office_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           transactions=transactions,
                           brand_color=config['color'],
                           logo_url=config['logo'])

# --- NEW: EMAIL SENDING ROUTE ---
@office_bp.route('/office/send-receipt/<int:transaction_id>')
def send_receipt(transaction_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    
    # In a real app, you would fetch the client's email from the database
    # For now, we will send it to the logged-in user or a test email
    # You can update this later to be dynamic
    user_email = "test_client@example.com" 
    
    # Prepare the email content
    subject = f"Receipt for Transaction #{transaction_id}"
    body = f"""
    <h2>Transaction Receipt</h2>
    <p>This is a confirmation for transaction #{transaction_id}.</p>
    <p>Thank you for your business.</p>
    <br>
    <p>Kind Regards,<br>The TradeCore Team</p>
    """
    
    # CALL THE ENGINE
    success, message = send_company_email(company_id, user_email, subject, body)
    
    if success:
        flash(f"✅ Email sent successfully to {user_email}!")
    else:
        flash(f"❌ Email Failed: {message}")
        
    return redirect(url_for('office.office_dashboard'))