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
    cur.execute("""
        SELECT ref, description, site_address, status, client_id, quote_total 
        FROM jobs 
        WHERE id = %s
    """, (job_id,))
    job_row = cur.fetchone()
    
    if not job_row:
        conn.close()
        return "Job not found", 404
    
    quote_amount = job_row[5] if job_row[5] else 0.0
    
    # 3. THE MASTER UNION QUERY (Merges 5 Sources)
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

        UNION ALL
        
        SELECT 'Timesheet', s.name || ' (' || t.hours || ' hrs)', (t.hours * s.pay_rate), t.date, 'No Link', t.id
        FROM staff_timesheets t
        JOIN staff s ON t.staff_id = s.id
        WHERE t.job_id = %s
        
        ORDER BY date DESC
    """, (job_id, job_id, job_id, job_id, job_id))
    
    files = cur.fetchall()
    
    # 4. Calculate Financials
    total_cost = sum(f[2] for f in files if f[0] in ['Expense / Receipt', 'Site Material', 'Timesheet'] and f[2])
    total_billed = sum(f[2] for f in files if f[0] == 'Client Invoice' and f[2])
    
    revenue_baseline = max(quote_amount, total_billed)
    profit = revenue_baseline - total_cost
    budget_remaining = quote_amount - total_cost
    
    # 5. Get Staff List (MOVED UP before closing connection)
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (session.get('company_id'),))
    staff_list = cur.fetchall()
    
    # 6. NOW Close the connection
    conn.close()
    
    return render_template('office/job_files.html', 
                           job=job_row, 
                           files=files, 
                           total_cost=total_cost, 
                           total_billed=total_billed,
                           profit=profit,
                           quote_total=quote_amount,
                           budget_remaining=budget_remaining,
                           staff=staff_list)

# --- MANUAL COST ENTRY (For Labor/Misc) ---
@jobs_bp.route('/office/job/<job_ref>/add-manual-cost', methods=['POST'])
def add_manual_cost(job_ref):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Get Job ID from Ref
        cur.execute("SELECT id FROM jobs WHERE ref = %s", (job_ref,))
        res = cur.fetchone()
        if not res: return "Job not found", 404
        job_id = res[0]
        
        desc = request.form.get('description')
        cost = request.form.get('cost')
        
        # Insert as an Expense (with 'Manual Entry' as the receipt path)
        cur.execute("""
            INSERT INTO job_expenses (company_id, job_id, description, cost, date, receipt_path)
            VALUES (%s, %s, %s, %s, CURRENT_DATE, 'Manual Entry')
        """, (session.get('company_id'), job_id, desc, cost))
        
        conn.commit()
        flash(f"✅ Added cost: £{cost}", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(f"/office/job/{job_id}/files")

# --- DELETE ITEM (Updated with Path Fix) ---
@jobs_bp.route('/office/job/delete-item/<int:item_id>/<path:item_type>')
def delete_job_item(item_id, item_type):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Determine which table to delete from
        if 'Invoice' in item_type:
             flash("⚠️ Cannot delete Invoices from here. Go to Finance > Invoices.", "warning")
        elif 'Expense' in item_type or 'Receipt' in item_type or 'Manual' in item_type:
            cur.execute("DELETE FROM job_expenses WHERE id = %s", (item_id,))
            flash("🗑️ Expense/Receipt Deleted", "success")
        elif 'Photo' in item_type or 'Evidence' in item_type:
            cur.execute("DELETE FROM job_evidence WHERE id = %s", (item_id,))
            flash("🗑️ Photo Deleted", "success")
        elif 'Material' in item_type:
             cur.execute("DELETE FROM job_materials WHERE id = %s", (item_id,))
             flash("🗑️ Material Removed", "success")
             
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(request.referrer)
    
    # --- LOG TIMESHEET (Staff Hours) ---
@jobs_bp.route('/office/job/<int:job_id>/log-hours', methods=['POST'])
def log_hours(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        staff_id = request.form.get('staff_id')
        hours = request.form.get('hours')
        date_worked = request.form.get('date')
        
        # Insert into staff_timesheets
        # Note: We rely on the database knowing the pay_rate from the staff table later
        cur.execute("""
            INSERT INTO staff_timesheets (company_id, staff_id, job_id, hours, date, status)
            VALUES (%s, %s, %s, %s, %s, 'Approved')
        """, (session.get('company_id'), staff_id, job_id, hours, date_worked))
        
        conn.commit()
        flash(f"✅ Logged {hours} hours.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(f"/office/job/{job_id}/files")