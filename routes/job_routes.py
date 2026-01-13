from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db
from datetime import date

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
    # FIX: Changed 't.hours' to 't.total_hours' to match your database
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
        
        SELECT 'Timesheet', s.name || ' (' || COALESCE(t.total_hours, 0) || ' hrs)', (COALESCE(t.total_hours, 0) * s.pay_rate), t.date, 'No Link', t.id
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
    
    # 5. Get Staff List
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (session.get('company_id'),))
    staff_list = cur.fetchall()
    
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
        cur.execute("SELECT id FROM jobs WHERE ref = %s", (job_ref,))
        res = cur.fetchone()
        if not res: return "Job not found", 404
        job_id = res[0]
        
        desc = request.form.get('description')
        cost = request.form.get('cost')
        
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

# --- DELETE ITEM ---
@jobs_bp.route('/office/job/delete-item/<int:item_id>/<path:item_type>')
def delete_job_item(item_id, item_type):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
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
        hours = request.form.get('hours') # Form field name is still 'hours', which is fine
        date_worked = request.form.get('date')
        
        # FIX: Writing to 'total_hours' (Correct Database Column)
        cur.execute("""
            INSERT INTO staff_timesheets (company_id, staff_id, job_id, total_hours, date, status)
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
    
# --- CREATE MANUAL JOB ---
@jobs_bp.route('/office/job/create', methods=['POST'])
def create_job():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')
    
    try:
        client_id = request.form.get('client_id')
        description = request.form.get('description')
        engineer_id = request.form.get('engineer_id') or None
        start_date = request.form.get('start_date') or date.today()
        vehicle_id = request.form.get('vehicle_id') or None
        est_days = request.form.get('days') or 1
        
        cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s", (comp_id,))
        count = cur.fetchone()[0]
        ref = f"JOB-{1000 + count + 1}"

        cur.execute("""
            INSERT INTO jobs (
                company_id, client_id, engineer_id, vehicle_id, 
                ref, description, status, start_date, estimated_days
            )
            VALUES (%s, %s, %s, %s, %s, %s, 'Pending', %s, %s)
            RETURNING id
        """, (comp_id, client_id, engineer_id, vehicle_id, ref, description, start_date, est_days))
        
        new_job_id = cur.fetchone()[0]
        conn.commit()
        
        flash(f"✅ Job {ref} Created Successfully", "success")
        return redirect(f"/office/job/{new_job_id}/files")

    except Exception as e:
        conn.rollback()
        flash(f"Error creating job: {e}", "error")
        return redirect(request.referrer or '/clients')
    finally:
        conn.close()