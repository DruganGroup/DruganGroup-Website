from flask import Blueprint, render_template, session, redirect, url_for
from db import get_db, get_site_config  # IMPORTED BRANDING TOOL

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
    
    # Get Recent Jobs
    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 10", (company_id,))
    transactions = cur.fetchall()
    conn.close()

    # Renders the template with BRANDING DATA passed in
    return render_template('office/office_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           transactions=transactions,
                           brand_color=config['color'],  # PASS COLOR
                           logo_url=config['logo'])      # PASS LOGO