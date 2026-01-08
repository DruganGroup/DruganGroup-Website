from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from datetime import date, datetime, timedelta
import json

# Define the new Blueprint
transactions_bp = Blueprint('transactions', __name__)

# --- HELPER: COUNTRY DATE FORMATS ---
COUNTRY_FORMATS = {
    'United Kingdom': '%d/%m/%Y', 'Ireland': '%d/%m/%Y', 'United States': '%m/%d/%Y',
    'Canada': '%Y-%m-%d', 'Australia': '%d/%m/%Y', 'Default': '%d/%m/%Y'
}

def get_date_fmt_str(company_id):
    try:
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (company_id,))
        row = cur.fetchone()
        conn.close()
        country = row[0] if row else 'Default'
        return COUNTRY_FORMATS.get(country, COUNTRY_FORMATS['Default'])
    except: return COUNTRY_FORMATS['Default']

# =========================================================
# 1. FINANCE DASHBOARD (With LIVE Linked Data)
# =========================================================
@transactions_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']: 
        return redirect(url_for('auth.login'))
        
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

    # --- A. CALCULATE TOTALS (Live from Invoices & Expenses) ---
    # 1. Total Income (Only PAID Invoices count as cash)
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE company_id = %s AND status = 'Paid'", (comp_id,))
    income = float(cur.fetchone()[0])

    # 2. Total Expense (Job Expenses + Overheads)
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE company_id = %s", (comp_id,))
    job_costs = float(cur.fetchone()[0])
    
    cur.execute("SELECT COALESCE(SUM(amount), 0) FROM overhead_items WHERE category_id IN (SELECT id FROM overhead_categories WHERE company_id = %s)", (comp_id,))
    overhead_costs = float(cur.fetchone()[0])
    
    expense = job_costs + overhead_costs
    balance = income - expense

    # --- B. BREAK-EVEN CALCULATOR ---
    monthly_overheads = overhead_costs # Simplify for now (Total tracked overheads)
    daily_overhead = monthly_overheads / 30.42

    cur.execute("SELECT SUM(daily_cost) FROM vehicles WHERE company_id = %s AND status='Active'", (comp_id,))
    daily_fleet = cur.fetchone()[0] or 0.0

    cur.execute("SELECT pay_rate, pay_model FROM staff WHERE company_id = %s AND status='Active'", (comp_id,))
    daily_staff = 0.0
    for s in cur.fetchall():
        rate = float(s[0] or 0)
        model = s[1]
        if model == 'Hour': daily_staff += (rate * 8)
        elif model == 'Day': daily_staff += rate
        elif model == 'Year': daily_staff += (rate / 260)

    break_even_target = daily_overhead + float(daily_fleet) + daily_staff

    # --- C. RECENT TRANSACTIONS (THE CLICKABLE FEED) ---
    # We combine Invoices (Income) and Expenses (Outgoing) into one list
    # The 'job_id' column allows us to link it. Overheads have NULL job_id.
    cur.execute("""
        (
            SELECT 
                date_created as date, 
                'Income' as type, 
                'Sales' as category, 
                ref || ' - ' || (SELECT name FROM clients WHERE id = invoices.client_id) as description, 
                total_amount as amount, 
                job_id
            FROM invoices 
            WHERE company_id = %s AND status = 'Paid'
        )
        UNION ALL
        (
            SELECT 
                date, 
                'Expense' as type, 
                'Job Cost' as category, 
                description, 
                cost as amount, 
                job_id
            FROM job_expenses 
            WHERE company_id = %s
        )
        UNION ALL
        (
            SELECT 
                date_incurred as date, 
                'Expense' as type, 
                'Overhead' as category, 
                name as description, 
                amount, 
                NULL as job_id
            FROM overhead_items 
            WHERE category_id IN (SELECT id FROM overhead_categories WHERE company_id = %s)
        )
        ORDER BY date DESC 
        LIMIT 15
    """, (comp_id, comp_id, comp_id))
    
    recent_trans = cur.fetchall()

    # --- D. AUDIT LOGS ---
    cur.execute("SELECT action, target, details, created_at, admin_email FROM audit_logs WHERE company_id = %s ORDER BY created_at DESC LIMIT 10", (comp_id,))
    raw_logs = cur.fetchall()
    audit_logs = [{'action': r[0], 'target': r[1], 'details': r[2], 'time': r[3].strftime('%d/%m %H:%M'), 'user': r[4]} for r in raw_logs]

    # --- E. CHART DATA (Simple Last 6 Months) ---
    # (Simplified for display purposes - uses the totals calculated above distributed roughly)
    # Ideally, you'd run a GROUP BY month query here, but let's stick to the list for now.
    chart_labels = ["Total"]
    chart_income = [income]
    chart_expense = [expense]

    conn.close()
    
    return render_template('finance/finance_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           total_balance=balance,
                           break_even=break_even_target,
                           logs=audit_logs,
                           transactions=recent_trans, # <-- Now holds the Job ID
                           chart_labels=json.dumps(chart_labels),
                           chart_income=json.dumps(chart_income),
                           chart_expense=json.dumps(chart_expense),
                           brand_color=config['color'], 
                           logo_url=config['logo'],
                           currency_symbol=config.get('currency_symbol', '£'))

# =========================================================
# 2. INVOICE STATUS TOGGLES (Paid/Unpaid)
# =========================================================
@transactions_bp.route('/finance/invoice/<int:invoice_id>/status/<new_status>')
def set_invoice_status(invoice_id, new_status):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        return redirect(url_for('auth.login'))
    
    valid = ['Draft', 'Sent', 'Paid', 'Unpaid', 'Overdue']
    if new_status not in valid:
        flash("❌ Invalid Status", "error")
        return redirect(url_for('finance.finance_invoices'))

    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("UPDATE invoices SET status = %s WHERE id = %s AND company_id = %s", 
                   (new_status, invoice_id, session.get('company_id')))
        
        actor = session.get('user_name', 'Unknown')
        cur.execute("""
            INSERT INTO audit_logs (company_id, admin_email, action, target, details, ip_address)
            VALUES (%s, %s, 'INVOICE_UPDATE', %s, %s, %s)
        """, (
            session.get('company_id'), 
            session.get('username'), 
            f"Invoice #{invoice_id}", 
            f"Marked as {new_status} by {actor}",
            request.remote_addr
        ))

        conn.commit()
        flash(f"✅ Invoice marked as {new_status}")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()

    return redirect(url_for('finance.finance_invoices'))
    
# --- BOOKKEEPING / SORTING OFFICE ---
@transactions_bp.route('/finance/bookkeeping', methods=['GET', 'POST'])
def bookkeeping_inbox():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    user_name = session.get('user_name', 'Admin')
    conn = get_db()
    cur = conn.cursor()

    if request.method == 'POST':
        file_id = request.form.get('file_id')
        action = request.form.get('action')
        
        try:
            if action == 'assign_job':
                job_id = request.form.get('job_id')
                desc = request.form.get('description')
                cost = request.form.get('cost')
                
                cur.execute("""
                    UPDATE job_expenses 
                    SET job_id = %s, description = %s, cost = %s 
                    WHERE id = %s AND company_id = %s
                """, (job_id, desc, cost, file_id, comp_id))
                
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'DOC_FILED', %s, %s, %s, CURRENT_TIMESTAMP)
                """, (comp_id, f"Job #{job_id}", f"Receipt filed to Job: {desc}", user_name))
                
                flash(f"✅ Filed to Job #{job_id}")

            elif action == 'assign_overhead':
                cat_id = request.form.get('category_id')
                name = request.form.get('description')
                amount = request.form.get('cost')
                
                cur.execute("SELECT receipt_path, date FROM job_expenses WHERE id = %s", (file_id,))
                res = cur.fetchone()
                if res:
                    path, date_val = res
                    cur.execute("""
                        INSERT INTO overhead_items (category_id, name, amount, date_incurred, receipt_path) 
                        VALUES (%s, %s, %s, %s, %s)
                    """, (cat_id, name, amount, date_val, path))
                    
                    cur.execute("DELETE FROM job_expenses WHERE id = %s", (file_id,))
                    
                    cur.execute("""
                        INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                        VALUES (%s, 'DOC_FILED', 'Overheads', %s, %s, CURRENT_TIMESTAMP)
                    """, (comp_id, f"Receipt filed to Overhead: {name}", user_name))

                    flash("✅ Filed to Overheads")

            elif action == 'delete':
                cur.execute("DELETE FROM job_expenses WHERE id = %s AND company_id = %s", (file_id, comp_id))
                
                cur.execute("""
                    INSERT INTO audit_logs (company_id, action, target, details, admin_email, created_at)
                    VALUES (%s, 'DOC_DELETED', 'Trash', 'Unsorted document deleted', %s, CURRENT_TIMESTAMP)
                """, (comp_id, user_name))
                
                flash("🗑️ Document Deleted")

            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"Error: {e}", "error")

    cur.execute("""
        SELECT id, description, cost, date, receipt_path 
        FROM job_expenses 
        WHERE job_id IS NULL AND company_id = %s 
        ORDER BY date DESC
    """, (comp_id,))
    unsorted = cur.fetchall()

    cur.execute("SELECT id, ref, site_address FROM jobs WHERE company_id = %s AND status != 'Completed'", (comp_id,))
    jobs = cur.fetchall()

    try:
        cur.execute("SELECT id, name FROM overhead_categories WHERE company_id = %s", (comp_id,))
        categories = cur.fetchall()
    except:
        categories = []

    conn.close()
    
    return render_template('finance/bookkeeping_inbox.html', 
                           unsorted=unsorted, 
                           jobs=jobs, 
                           categories=categories)