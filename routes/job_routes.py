from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db

# Define the Blueprint
jobs_bp = Blueprint('jobs', __name__)

from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db

# Define the Blueprint
jobs_bp = Blueprint('jobs', __name__)

# --- VIEW JOB FILE PACK (The Digital Binder) ---
@jobs_bp.route('/office/job/<int:job_id>/files')
def job_files(job_id):
    # 1. Security Check
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    # 2. Get Job Details
    cur.execute("SELECT ref, description, site_address, status, client_id FROM jobs WHERE id = %s", (job_id,))
    job = cur.fetchone()
    
    if not job:
        conn.close()
        return "Job not found", 404
    
    # 3. THE MASTER UNION QUERY (Merges 4 Sources)
    cur.execute("""
        SELECT 'Client Invoice' as type, ref as name, total_amount as cost, date_created as date, 'Generated' as path, id 
        FROM invoices WHERE job_id = %s
        
        UNION ALL
        
        SELECT 'Expense / Receipt', description, cost, date, receipt_path, id 
        FROM job_expenses WHERE job_id = %s
        
        UNION ALL
        
        SELECT 'Site Photo', 'Evidence Upload', 0, uploaded_at::DATE, filepath, id
        FROM job_evidence WHERE job_id = %s
        
        UNION ALL
        
        SELECT 'Site Material', description || ' (x' || quantity || ')', (unit_price * quantity), added_at::DATE, 'Material', id
        FROM job_materials WHERE job_id = %s
        
        ORDER BY date DESC
    """, (job_id, job_id, job_id, job_id))
    
    files = cur.fetchall()
    
    # 4. Calculate Financials
    total_cost = sum(f[2] for f in files if f[0] in ['Expense / Receipt', 'Site Material'] and f[2])
    total_billed = sum(f[2] for f in files if f[0] == 'Client Invoice' and f[2])
    profit = total_billed - total_cost
    
    conn.close()
    
    return render_template('office/job_files.html', 
                           job=job, 
                           files=files, 
                           total_cost=total_cost, 
                           total_billed=total_billed,
                           profit=profit)

# --- CONVERT JOB TO INVOICE (New Logic) ---
@jobs_bp.route('/office/job/<int:job_id>/invoice', methods=['GET', 'POST'])
def job_to_invoice(job_id):
    # 1. Security Check
    if not session.get('user_id'): return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')

    # 2. Check if Invoice Already Exists
    cur.execute("SELECT id FROM invoices WHERE job_id = %s", (job_id,))
    existing = cur.fetchone()
    if existing:
        flash("ℹ️ Invoice already exists for this job.", "info")
        # Ensure you have 'pdf.download_invoice_pdf' route available
        return redirect(url_for('pdf.download_invoice_pdf', invoice_id=existing[0]))

    # 3. Fetch Job Data
    cur.execute("SELECT client_id, description, status FROM jobs WHERE id = %s AND company_id = %s", (job_id, comp_id))
    job = cur.fetchone()
    
    if not job:
        conn.close()
        return "Job not found", 404

    client_id = job[0]
    job_desc = job[1]

    # 4. Fetch Settings (Markup & Payment Days)
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s AND key IN ('default_markup', 'payment_days')", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # Calculate Markup Multiplier (e.g. 20% becomes 1.20)
    markup_percent = float(settings.get('default_markup', 20))
    markup_multiplier = 1 + (markup_percent / 100)
    
    # Get Payment Days (Default to 14 if missing)
    payment_days = int(settings.get('payment_days', 14))

    # 5. Create The Invoice Record
    ref_number = f"INV-JOB-{job_id}"
    
    try:
        cur.execute(f"""
            INSERT INTO invoices (company_id, client_id, job_id, ref, date_created, due_date, status, total_amount)
            VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '{payment_days} days', 'Unpaid', 0.00)
            RETURNING id
        """, (comp_id, client_id, job_id, ref_number))
        
        new_invoice_id = cur.fetchone()[0]

        # 6. Transfer Expenses -> Invoice Items (Applying Markup)
        # Note: We are using 'job_expenses' here to match your Binder logic
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            SELECT %s, description, 1, (cost * %s), (cost * %s)
            FROM job_expenses 
            WHERE job_id = %s
        """, (new_invoice_id, markup_multiplier, markup_multiplier, job_id))

        # 7. Add Labor Line (Placeholder)
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, 1, 0.00, 0.00)
        """, (new_invoice_id, f"Labor / Works for Job #{job_id}: {job_desc}"))

        # 8. Update Total
        cur.execute("""
            UPDATE invoices 
            SET total_amount = (SELECT COALESCE(SUM(total), 0) FROM invoice_items WHERE invoice_id = %s)
            WHERE id = %s
        """, (new_invoice_id, new_invoice_id))
        
        # 9. Mark Job as Invoiced
        cur.execute("UPDATE jobs SET status = 'Invoiced' WHERE id = %s", (job_id,))

        conn.commit()
        flash(f"✅ Invoice {ref_number} Generated (Markup: {markup_percent}%, Due: {payment_days} days)", "success")
        return redirect(url_for('finance.finance_invoices'))

    except Exception as e:
        conn.rollback()
        flash(f"Error creating invoice: {e}", "error")
        return redirect(url_for('office.office_dashboard'))
    finally:
        conn.close()