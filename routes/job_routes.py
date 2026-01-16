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
    comp_id = session.get('company_id')
    
    # 2. Get Job Details (UPDATED: Now fetches Job Title from Quote)
    cur.execute("""
        SELECT 
            j.ref, 
            j.description, 
            COALESCE(p.address_line1, j.site_address, 'No Address Logged') as address, 
            j.status, 
            j.quote_id, 
            COALESCE(j.quote_total, 0),
            c.name,
            c.email,
            c.phone,
            q.job_title   -- Fetching the Title from the linked Quote
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id
        LEFT JOIN properties p ON j.property_id = p.id
        LEFT JOIN quotes q ON j.quote_id = q.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    
    job_row = cur.fetchone()
    
    if not job_row:
        conn.close()
        return "Job not found", 404
    
    # Create the job dictionary
    # Logic: If we have a Quote Title, use it. If not, use "Job <Ref>"
    display_title = job_row[9] if job_row[9] else f"Job {job_row[0]}"

    job = {
        'id': job_id,
        'ref': job_row[0],
        'desc': job_row[1],
        'address': job_row[2],
        'status': job_row[3],
        'client': job_row[6] or "Unknown Client",
        'email': job_row[7],
        'phone': job_row[8],
        'title': display_title 
    }
    quote_id, quote_total = job_row[4], float(job_row[5])
    
    # 3. FINANCIALS (Calculations)
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE job_id = %s AND status != 'Void'", (job_id,))
    total_billed = float(cur.fetchone()[0])
    
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE job_id = %s", (job_id,))
    expenses = float(cur.fetchone()[0])
    
    cur.execute("SELECT COALESCE(SUM(quantity * unit_price), 0) FROM job_materials WHERE job_id = %s", (job_id,))
    materials_cost = float(cur.fetchone()[0])
    
    cur.execute("SELECT COALESCE(SUM(t.total_hours * s.pay_rate), 0) FROM staff_timesheets t JOIN staff s ON t.staff_id = s.id WHERE t.job_id = %s", (job_id,))
    labour = float(cur.fetchone()[0])
    
    total_cost = expenses + materials_cost + labour
    profit = quote_total - total_cost
    budget_remaining = quote_total - total_cost
    
    # 4. ASSEMBLE FILES LIST
    files = []
    
    # Invoices
    cur.execute("SELECT id, ref, total_amount, date_created FROM invoices WHERE job_id = %s ORDER BY date_created DESC", (job_id,))
    for r in cur.fetchall(): files.append(('Client Invoice', r[1], float(r[2]), str(r[3]), 'invoice', r[0]))

    # Expenses
    cur.execute("SELECT description, cost, date, receipt_path, id FROM job_expenses WHERE job_id = %s ORDER BY date DESC", (job_id,))
    for r in cur.fetchall(): files.append(('Expense', r[0], float(r[1]), str(r[2]), r[3] or 'No Link', r[4]))
        
    # Materials
    cur.execute("SELECT description, quantity, unit_price, date_added, id FROM job_materials WHERE job_id = %s ORDER BY date_added DESC", (job_id,))
    for r in cur.fetchall(): files.append(('Material', f"{r[1]}x {r[0]}", float(r[1])*float(r[2]), str(r[3]), 'Material', r[4]))

    # Timesheets
    cur.execute("SELECT t.id, s.name, t.total_hours, s.pay_rate, t.date FROM staff_timesheets t JOIN staff s ON t.staff_id = s.id WHERE t.job_id = %s ORDER BY t.date DESC", (job_id,))
    for r in cur.fetchall(): 
        hours = float(r[2]) if r[2] else 0.0
        cost = hours * float(r[3])
        files.append(('Timesheet', f"Labor: {r[1]} ({hours} hrs)", cost, str(r[4]), 'No Link', r[0]))

    # Photos
    cur.execute("SELECT id, filepath, uploaded_at::DATE FROM job_evidence WHERE job_id = %s ORDER BY uploaded_at DESC", (job_id,))
    for r in cur.fetchall():
        files.append(('Site Photo', 'Evidence Photo', 0.0, str(r[2]), r[1], r[0]))

    # Sort all by date (Newest First)
    files.sort(key=lambda x: x[3], reverse=True)
    
    # 5. Get Staff List
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff_list = cur.fetchall()
    
    conn.close()
    
    return render_template('office/job_files.html', 
                           job=job, 
                           files=files, 
                           total_cost=total_cost, 
                           total_billed=total_billed,
                           profit=profit,
                           quote_id=quote_id,
                           quote_total=quote_total,
                           budget_remaining=budget_remaining,
                           staff=staff_list,
                           today=date.today())

# --- MANUAL COST ENTRY ---
@jobs_bp.route('/office/job/<job_ref>/add-manual-cost', methods=['POST'])
def add_manual_cost(job_ref):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        if job_ref.isdigit():
            job_id = int(job_ref)
        else:
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
    
# --- LOG TIMESHEET ---
@jobs_bp.route('/office/job/<int:job_id>/log-hours', methods=['POST'])
def log_hours(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        staff_id = request.form.get('staff_id')
        hours = request.form.get('hours') 
        date_worked = request.form.get('date')
        
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
        
        property_id = request.form.get('property_id') or None

        cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s", (comp_id,))
        count = cur.fetchone()[0]
        ref = f"JOB-{1000 + count + 1}"

        cur.execute("""
            INSERT INTO jobs (
                company_id, client_id, property_id, engineer_id, vehicle_id, 
                ref, description, status, start_date, estimated_days
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'Pending', %s, %s)
            RETURNING id
        """, (comp_id, client_id, property_id, engineer_id, vehicle_id, ref, description, start_date, est_days))
        
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