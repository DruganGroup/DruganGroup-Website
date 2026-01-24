from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db
from datetime import date

jobs_bp = Blueprint('jobs', __name__)

@jobs_bp.route('/office/job/create')
def create_job():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')
    
    # 1. Fetch Lists for Dropdowns
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name ASC", (comp_id,))
    clients = cur.fetchall()
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id = %s AND status = 'Active' ORDER BY reg_plate ASC", (comp_id,))
    vehicles = cur.fetchall()
    
    # 2. Handle Pre-selection (Client & Property)
    pre_client_id = request.args.get('client_id')
    pre_prop_id = request.args.get('property_id')
    
    properties = []
    target_client = None
    target_property = None

    if pre_client_id:
        cur.execute("SELECT id, address_line1, postcode FROM properties WHERE client_id = %s ORDER BY address_line1 ASC", (pre_client_id,))
        properties = cur.fetchall()
        
        cur.execute("SELECT * FROM clients WHERE id = %s", (pre_client_id,))
        target_client = cur.fetchone()

    if pre_prop_id:
        cur.execute("SELECT * FROM properties WHERE id = %s", (pre_prop_id,))
        target_property = cur.fetchone()
        
    conn.close()
    
    return render_template('office/job/create_job.html',
                           clients=clients, 
                           vehicles=vehicles, 
                           properties=properties,
                           pre_client_id=pre_client_id,
                           pre_prop_id=pre_prop_id,
                           client=target_client,
                           property=target_property)

@jobs_bp.route('/office/job/<int:job_id>/files')
def job_files(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')
    
    # 1. Get Job Details (Fetching Vehicle Daily Cost too)
    cur.execute("""
        SELECT 
            j.ref, j.description, j.site_address, j.status, 
            j.quote_id, COALESCE(j.quote_total, 0),
            c.name, c.email, c.phone, q.job_title,
            v.daily_cost, v.reg_plate  -- <--- NEW: Get Van Cost
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id
        LEFT JOIN quotes q ON j.quote_id = q.id
        LEFT JOIN vehicles v ON j.vehicle_id = v.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    
    job_row = cur.fetchone()
    if not job_row:
        conn.close(); return "Job not found", 404
    
    van_daily_cost = float(job_row[10]) if job_row[10] else 0.0
    van_reg = job_row[11] or "No Vehicle"

    job = {
        'id': job_id, 'ref': job_row[0], 'desc': job_row[1], 'address': job_row[2],
        'status': job_row[3], 'client': job_row[6], 'title': job_row[9] or f"Job {job_row[0]}"
    }
    quote_total = float(job_row[5])
    
    # 2. FINANCIALS
    # A. Invoices (Billed)
    cur.execute("SELECT COALESCE(SUM(total_amount), 0) FROM invoices WHERE job_id = %s AND status != 'Void'", (job_id,))
    total_billed = float(cur.fetchone()[0])
    
    # B. Expenses (Receipts)
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE job_id = %s", (job_id,))
    expenses = float(cur.fetchone()[0])
    
    # C. Materials
    cur.execute("SELECT COALESCE(SUM(quantity * unit_price), 0) FROM job_materials WHERE job_id = %s", (job_id,))
    materials_cost = float(cur.fetchone()[0])
    
    # D. Labor (Timesheets)
    cur.execute("""
        SELECT COALESCE(SUM(t.total_hours * s.pay_rate), 0), COUNT(DISTINCT t.date) 
        FROM staff_timesheets t 
        JOIN staff s ON t.staff_id = s.id 
        WHERE t.job_id = %s
    """, (job_id,))
    labor_data = cur.fetchone()
    labour_cost = float(labor_data[0])
    days_worked = int(labor_data[1]) # Count how many unique days people worked
    
    # E. Vehicle Cost (NEW CALCULATION)
    # We charge the van cost for every day the team was on site
    vehicle_cost = days_worked * van_daily_cost
    
    # Total Cost & Budget
    total_cost = expenses + materials_cost + labour_cost + vehicle_cost
    profit = quote_total - total_cost
    budget_remaining = quote_total - total_cost  # <--- PASSED TO TEMPLATE
    
    # 3. ASSEMBLE FILES LIST
    files = []
    
    # --- FETCH FILES (Invoices, Expenses, etc.) ---
    # Fetch Invoices
    cur.execute("SELECT id, reference, total_amount, date, status FROM invoices WHERE job_id = %s", (job_id,))
    for row in cur.fetchall():
        files.append(('Invoice', row[1], row[2], str(row[3]), row[4], row[0]))

    # Fetch Expenses
    cur.execute("SELECT id, description, cost, date, receipt_path FROM job_expenses WHERE job_id = %s", (job_id,))
    for row in cur.fetchall():
        files.append(('Expense', row[1], row[2], str(row[3]), row[4], row[0]))

    # Fetch Materials
    cur.execute("SELECT id, description, (quantity * unit_price), added_at FROM job_materials WHERE job_id = %s", (job_id,))
    for row in cur.fetchall():
        files.append(('Material', row[1], row[2], str(row[3])[:10], 'Logged', row[0]))

    # Fetch Photos/Evidence
    # FIX: Use 'filepath' based on schema
    cur.execute("SELECT id, filepath, uploaded_at, file_type FROM job_evidence WHERE job_id = %s", (job_id,))
    for row in cur.fetchall():
        f_type = row[3] if row[3] else "Photo"
        files.append((f_type, "Evidence Upload", 0, str(row[2])[:10], row[1], row[0]))

    # 4. Add a "Virtual" receipt for the Van Cost so it shows in the list
    if vehicle_cost > 0:
        files.append(('Vehicle', f"Fleet Charge: {van_reg} ({days_worked} days)", vehicle_cost, str(date.today()), 'Auto-Calc', 0))

    files.sort(key=lambda x: x[3], reverse=True)
    
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff_list = cur.fetchall()
    conn.close()
    
    return render_template('office/job_files.html', 
                           job=job, files=files, 
                           total_cost=total_cost, total_billed=total_billed,
                           profit=profit, quote_total=quote_total,
                           budget_remaining=budget_remaining, 
                           staff=staff_list, today=date.today())

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
    
@jobs_bp.route('/office/job/save', methods=['POST'])
def save_job_action():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')
    
    try:
        # 1. Capture Form Data
        client_id = request.form.get('client_id')
        description = request.form.get('description')
        property_id = request.form.get('property_id') or None
        vehicle_id = request.form.get('vehicle_id') or None
        est_days = request.form.get('days') or 1
        
        # FIX 1: DATE LOGIC
        start_date = request.form.get('start_date') or None 

        # FIX 2: DRIVER LOOKUP
        engineer_id = None
        if vehicle_id:
            cur.execute("SELECT assigned_driver_id FROM vehicles WHERE id = %s", (vehicle_id,))
            row = cur.fetchone()
            if row and row[0]:
                engineer_id = row[0]  # Found him!

        # 3. Generate Reference
        cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s", (comp_id,))
        count = cur.fetchone()[0]
        ref = f"JOB-{1000 + count + 1}"

        # 4. Insert the Job
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
        return redirect(request.referrer or '/office-hub')
    finally:
        conn.close()