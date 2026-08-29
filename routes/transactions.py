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
        pass
        country = row[0] if row else 'Default'
        return COUNTRY_FORMATS.get(country, COUNTRY_FORMATS['Default'])
    except: return COUNTRY_FORMATS['Default']

# =========================================================
# 1. FINANCE DASHBOARD (With LIVE Linked Data)
# =========================================================
from services.dashboard_service import get_finance_dashboard_data

@transactions_bp.route('/finance-dashboard')
def finance_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']: 
        return redirect(url_for('auth.login'))
        
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    data = get_finance_dashboard_data(comp_id)

    return render_template('finance/finance_dashboard.html',
                           currency_symbol=data.get('currency_symbol', '£'),
                           total_income=data.get('total_income', 0),
                           total_invoiced=data.get('total_invoiced', 0),
                           pending_income=data.get('pending_income', 0),
                           total_wages=data.get('total_wages', 0),
                           ytd_wages=data.get('ytd_wages', 0),
                           fleet_cost=data.get('fleet_cost', 0),
                           overhead_costs=data.get('overhead_costs', 0),
                           job_expenses_cost=data.get('job_expenses_cost', 0),
                           total_expense=data.get('total_expense', 0),
                           total_balance=data.get('total_balance', 0),
                           profit_margin=data.get('profit_margin', 0),
                           break_even=data.get('break_even', 0),
                           yearly_summary=data.get('yearly_summary', []),
                           transactions=data.get('transactions', []),
                           logs=data.get('logs', []),
                           chart_labels=data.get('chart_labels', []),
                           chart_income=data.get('chart_income', []),
                           chart_expense=data.get('chart_expense', []),
                           brand_color=config['color'],
                           logo_url=config['logo'])

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
        pass

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

    pass
    
    return render_template('finance/bookkeeping_inbox.html', 
                           unsorted=unsorted, 
                           jobs=jobs, 
                           categories=categories)