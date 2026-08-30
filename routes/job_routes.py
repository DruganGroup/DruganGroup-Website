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
    
    # 2. Handle Pre-selection
    pre_client_id = request.args.get('client_id')
    pre_prop_id = request.args.get('property_id')
    
    properties = []
    target_client = None
    target_property = None

    if pre_client_id:
        # Get properties for dropdown
        cur.execute("SELECT id, address_line1, postcode FROM properties WHERE client_id = %s ORDER BY address_line1 ASC", (pre_client_id,))
        properties = cur.fetchall()
        
        # Get Client (Select * works here because Name is usually index 1)
        cur.execute("SELECT * FROM clients WHERE id = %s", (pre_client_id,))
        target_client = cur.fetchone()

    if pre_prop_id:
        cur.execute("SELECT id, address_line1, postcode FROM properties WHERE id = %s", (pre_prop_id,))
        target_property = cur.fetchone()
        
    pass
    
    # 3. Render
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
    
    from services.pricing_engine import get_company_markups, get_effective_vehicle_gang_cost, calculate_service_request_estimate

    # 1. Get Job Details (Fetching Vehicle and Staff assignments)
    cur.execute("""
        SELECT 
            j.ref, j.description, j.site_address, j.status, 
            j.quote_id, COALESCE(j.quote_total, 0),
            c.name, c.email, c.phone, q.job_title,
            v.daily_cost, v.reg_plate, j.property_id, p.key_code,
            j.vehicle_id, j.engineer_id, c.id
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id
        LEFT JOIN quotes q ON j.quote_id = q.id
        LEFT JOIN vehicles v ON j.vehicle_id = v.id
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    
    job_row = cur.fetchone()
    if not job_row:
        return "Job not found", 404
    
    assigned_veh_id = job_row[14]
    assigned_eng_id = job_row[15]
    client_id = job_row[16]

    # Calculate True Gang Cost (Vehicle + Driver + Crew)
    veh_id, van_reg, van_daily_cost = get_effective_vehicle_gang_cost(cur, comp_id, vehicle_id=assigned_veh_id, engineer_id=assigned_eng_id)

    job = {
        'id': job_id, 'ref': job_row[0], 'desc': job_row[1], 'address': job_row[2],
        'status': job_row[3], 'client': job_row[6], 'title': job_row[9] or f"Job {job_row[0]}",
        'property_id': job_row[12] or '',
        'key_code': job_row[13] or '',
        'quote_id': job_row[4],
        'vehicle_id': assigned_veh_id,
        'engineer_id': assigned_eng_id,
        'van_reg': van_reg,
        'client_id': client_id
    }
    quote_total = float(job_row[5] or 0.0)
    
    # 2. FINANCIALS & MARKUPS
    labour_markup, material_markup = get_company_markups(cur, comp_id)

    # A. Invoices (Billed)
    cur.execute("SELECT COALESCE(SUM(total), 0) FROM invoices WHERE job_id = %s AND status != 'Void'", (job_id,))
    total_billed = float(cur.fetchone()[0] or 0)
    
    # B. Expenses (Receipts)
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM job_expenses WHERE job_id = %s", (job_id,))
    expenses = float(cur.fetchone()[0] or 0)
    
    # C. Materials (Cost & Billable with Markup)
    cur.execute("SELECT COALESCE(SUM(quantity * COALESCE(cost_price, unit_price, 0)), 0) FROM job_materials WHERE job_id = %s", (job_id,))
    materials_cost = float(cur.fetchone()[0] or 0)
    materials_billable = round(materials_cost * (1 + (material_markup / 100.0)), 2)
    
    # D. Labor (Timesheets with Pay Rates & Labour Markup)
    cur.execute("""
        SELECT 
            COALESCE(SUM(
                t.total_hours * 
                CASE
                    WHEN COALESCE(t.pay_model, s.pay_model) = 'Day' THEN (COALESCE(t.pay_rate, s.pay_rate, 0) / 8.0)
                    WHEN COALESCE(t.pay_model, s.pay_model) = 'Year' THEN (COALESCE(t.pay_rate, s.pay_rate, 0) / (260.0 * 8.0))
                    ELSE COALESCE(t.pay_rate, s.pay_rate, 0)
                END
            ), 0), 
            COUNT(DISTINCT t.date) 
        FROM staff_timesheets t 
        JOIN staff s ON t.staff_id = s.id 
        WHERE t.job_id = %s
    """, (job_id,))
    labor_data = cur.fetchone()
    labour_cost = float(labor_data[0] or 0)
    days_worked = int(labor_data[1] or 0)

    # Check active timer if today is currently in progress
    cur.execute("SELECT COUNT(*) FROM staff_timesheets WHERE job_id = %s AND clock_out IS NULL", (job_id,))
    active_timers = cur.fetchone()[0] or 0
    effective_days = max(days_worked, 1 if (active_timers > 0 or labour_cost > 0) else 0)

    labour_billable = round(labour_cost * (1 + (labour_markup / 100.0)), 2)
    
    # D2. Missing Pay Rate Check
    cur.execute("""
        SELECT COUNT(t.id) 
        FROM staff_timesheets t 
        JOIN staff s ON t.staff_id = s.id 
        WHERE t.job_id = %s AND (s.pay_rate IS NULL OR s.pay_rate = 0)
    """, (job_id,))
    missing_pay_rate_warning = (cur.fetchone()[0] or 0) > 0
    
    # E. Vehicle Cost (Gang Daily Run-Rate)
    vehicle_cost = round(effective_days * van_daily_cost, 2)
    vehicle_billable = round(vehicle_cost * (1 + (labour_markup / 100.0)), 2)
    
    # Total Actual Incurred Cost
    total_cost = round(expenses + materials_cost + labour_cost + vehicle_cost, 2)
    
    # Live Billable Total (Materials + Labour + Vehicle with Profit Markup)
    live_billable_total = round(materials_billable + labour_billable + vehicle_billable + expenses, 2)

    # If unquoted / CP12 / reported fault (quote_total == 0)
    if quote_total <= 0:
        if live_billable_total > 0:
            display_budget = live_billable_total
        else:
            default_est = calculate_service_request_estimate(cur, comp_id, job['desc'], job['property_id'])
            display_budget = default_est.get('estimated_price', 0.0)
    else:
        display_budget = quote_total

    profit = round(display_budget - total_cost, 2)
    budget_remaining = round(display_budget - total_cost, 2)
    
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
    cur.execute("SELECT id, description, (quantity * cost_price), added_at FROM job_materials WHERE job_id = %s", (job_id,))
    for row in cur.fetchall():
        files.append(('Material', row[1], row[2], str(row[3])[:10], 'Logged', row[0]))

    # Fetch Photos/Evidence
    # FIX: Use 'filepath' based on schema
    cur.execute("SELECT id, filepath, uploaded_at, file_type, visible_to_client FROM job_evidence WHERE job_id = %s", (job_id,))
    for row in cur.fetchall():
        f_type = row[3] if row[3] else "Photo"
        files.append((f_type, "Evidence Upload", 0, str(row[2])[:10], row[1], row[0], row[4]))

    # Fetch Timesheets for file list
    cur.execute("""
        SELECT t.id, s.name, t.total_hours, t.date,
               (COALESCE(t.total_hours, GREATEST(0, EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - t.clock_in))/3600.0)) * CASE
                    WHEN COALESCE(t.pay_model, s.pay_model) = 'Day' THEN (COALESCE(t.pay_rate, s.pay_rate, 0) / 8.0)
                    WHEN COALESCE(t.pay_model, s.pay_model) = 'Year' THEN (COALESCE(t.pay_rate, s.pay_rate, 0) / (260.0 * 8.0))
                    ELSE COALESCE(t.pay_rate, s.pay_rate, 0)
                END) as cost,
               t.clock_in
        FROM staff_timesheets t
        JOIN staff s ON t.staff_id = s.id
        WHERE t.job_id = %s
    """, (job_id,))
    for row in cur.fetchall():
        if row[2] is None:
            # Active timer
            cost = float(row[4] or 0.0)
            files.append(('Timesheet', f"{row[1]} (Clocked In)", cost, str(row[3])[:10] if row[3] else str(date.today()), 'Pending', row[0]))
        else:
            files.append(('Timesheet', f"{row[1]} ({float(row[2]):.1f} hrs)", float(row[4] or 0.0), str(row[3])[:10], 'Logged', row[0]))

    if vehicle_cost > 0:
        files.append(('Vehicle', f"Fleet Gang Charge: {van_reg} ({effective_days} days @ £{van_daily_cost:.2f}/day)", vehicle_cost, str(date.today()), 'Auto-Calc', 0))

    files.sort(key=lambda x: x[3], reverse=True)
    
    cur.execute("SELECT id, name FROM staff WHERE company_id = %s ORDER BY name", (comp_id,))
    staff_list = cur.fetchall()

    cur.execute("SELECT id, reg_plate, make_model, daily_cost FROM vehicles WHERE company_id = %s ORDER BY reg_plate", (comp_id,))
    vehicles_list = [{'id': r[0], 'reg': r[1], 'model': r[2] or '', 'cost': float(r[3] or 0)} for r in cur.fetchall()]

    # Site Diary (Notes left by site workers for the office)
    cur.execute("""
        SELECT staff_name, entry_text, created_at
        FROM site_diary WHERE job_id = %s ORDER BY created_at DESC
    """, (job_id,))
    diary = cur.fetchall()
    
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (comp_id,))
    country_row = cur.fetchone()
    country_code = country_row[0] if country_row else 'UK'
    
    from utils.certificates import get_certificates_for_country
    certificates = get_certificates_for_country(country_code)

    # Check if this job already has an invoice created
    cur.execute("SELECT id, reference, status, total FROM invoices WHERE job_id = %s AND company_id = %s AND status != 'Void' LIMIT 1", (job_id, comp_id))
    existing_inv_row = cur.fetchone()
    existing_invoice = {'id': existing_inv_row[0], 'ref': existing_inv_row[1], 'status': existing_inv_row[2], 'total': existing_inv_row[3]} if existing_inv_row else None
    
    return render_template('office/job_files.html', 
                           job=job, files=files, 
                           total_cost=total_cost, total_billed=total_billed,
                           profit=profit, quote_total=quote_total,
                           display_budget=display_budget,
                           live_billable_total=live_billable_total,
                           materials_billable=materials_billable,
                           labour_billable=labour_billable,
                           vehicle_billable=vehicle_billable,
                           van_daily_cost=van_daily_cost,
                           van_reg=van_reg,
                           vehicles=vehicles_list,
                           labour_markup=labour_markup,
                           material_markup=material_markup,
                           budget_remaining=budget_remaining, 
                           staff=staff_list, diary=diary, today=date.today(),
                           certificates=certificates, country_code=country_code,
                           existing_invoice=existing_invoice,
                           missing_pay_rate_warning=missing_pay_rate_warning)

@jobs_bp.route('/office/job/<int:job_id>/set-budget', methods=['POST'])
def set_job_budget(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    new_budget = float(request.form.get('budget_amount') or 0.0)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET quote_total = %s WHERE id = %s AND company_id = %s", (new_budget, job_id, comp_id))
    conn.commit()
    flash(f"✅ Job Budget updated to £{new_budget:.2f}", "success")
    return redirect(f"/office/job/{job_id}/files")

@jobs_bp.route('/office/job/<int:job_id>/assign-resources', methods=['POST'])
def assign_job_resources(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    veh_id = request.form.get('vehicle_id') or None
    eng_id = request.form.get('engineer_id') or None
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE jobs SET vehicle_id = %s, engineer_id = %s WHERE id = %s AND company_id = %s", (veh_id, eng_id, job_id, comp_id))
    conn.commit()
@jobs_bp.route('/office/job/<int:job_id>/generate-invoice', methods=['GET', 'POST'])
def generate_invoice_from_job(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT id, reference FROM invoices WHERE job_id = %s AND company_id = %s AND status != 'Void' LIMIT 1", (job_id, comp_id))
    inv_row = cur.fetchone()
    if inv_row:
        flash(f"ℹ️ Invoice #{inv_row[1]} already exists for this job.", "info")
        return redirect(f"/finance/invoice/{inv_row[0]}/view")

    cur.execute("""
        SELECT j.client_id, j.ref, j.description, j.vehicle_id, j.engineer_id, c.name
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    job_info = cur.fetchone()
    if not job_info:
        flash("Job not found.", "error")
        return redirect(url_for('office.office_dashboard'))
        
    client_id, job_ref, job_desc, veh_id, eng_id, client_name = job_info
    
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
    inv_count = cur.fetchone()[0]
    inv_ref = f"INV-{1000 + inv_count + 1}"
    
    cur.execute("""
        INSERT INTO invoices (company_id, client_id, reference, date, due_date, status, subtotal, tax, total, job_id, notes) 
        VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s, %s) 
        RETURNING id
    """, (comp_id, client_id, inv_ref, job_id, f"Invoiced for Job #{job_ref}: {job_desc}"))
    inv_id = cur.fetchone()[0]

    from services.pricing_engine import get_company_markups, get_effective_vehicle_gang_cost
    labour_markup, material_markup = get_company_markups(cur, comp_id)
    labour_mult = 1.0 + (labour_markup / 100.0)
    mat_mult = 1.0 + (material_markup / 100.0)

    cur.execute("""
        SELECT t.staff_id, s.name, SUM(t.total_hours), s.pay_rate, s.pay_model
        FROM staff_timesheets t
        JOIN staff s ON t.staff_id = s.id
        WHERE t.job_id = %s AND t.status IN ('Approved', 'Pending', 'Logged')
        GROUP BY t.staff_id, s.name, s.pay_rate, s.pay_model
    """, (job_id,))
    timesheets = cur.fetchall()

    for ts in timesheets:
        s_id, s_name, hours, raw_rate, pay_model = ts
        if not hours or float(hours) <= 0: continue
        hours = float(hours)
        raw_rate = float(raw_rate or 0)
        
        if pay_model == 'Day': base_rate = raw_rate / 8.0
        elif pay_model == 'Year': base_rate = raw_rate / (260.0 * 8.0)
        else: base_rate = raw_rate if raw_rate > 0 else 30.0
        
        charge_rate = round(base_rate * labour_mult, 2)
        line_total = round(hours * charge_rate, 2)
        
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, %s, %s, %s)
        """, (inv_id, f"Labour: {s_name} ({hours:.1f} hrs)", hours, charge_rate, line_total))

    cur.execute("SELECT description, quantity, cost_price, unit_price FROM job_materials WHERE job_id = %s", (job_id,))
    for mat in cur.fetchall():
        m_desc, m_qty, m_cost, m_unit = mat
        qty = float(m_qty or 1)
        base_unit = float(m_unit if (m_unit and float(m_unit) > 0) else (m_cost or 0))
        sell_price = round(base_unit * mat_mult if base_unit > 0 else 0, 2)
        line_tot = round(qty * sell_price, 2)
        
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, %s, %s, %s)
        """, (inv_id, f"Material: {m_desc}", qty, sell_price, line_tot))

    cur.execute("SELECT COUNT(DISTINCT date) FROM staff_timesheets WHERE job_id = %s", (job_id,))
    days_cnt = cur.fetchone()[0] or 1
    from services.pricing_engine import get_effective_vehicle_running_cost
    _, van_reg_name, daily_running_cost = get_effective_vehicle_running_cost(cur, comp_id, vehicle_id=veh_id, engineer_id=eng_id)
    if daily_running_cost > 0:
        van_sell_daily = round(daily_running_cost, 2)
        van_tot = round(days_cnt * van_sell_daily, 2)
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, %s, %s, %s)
        """, (inv_id, f"Vehicle & Equipment ({van_reg_name}) - {days_cnt} day(s)", days_cnt, van_sell_daily, van_tot))

    cur.execute("SELECT description, cost FROM job_expenses WHERE job_id = %s", (job_id,))
    for exp in cur.fetchall():
        e_desc, e_cost = exp
        e_amt = float(e_cost or 0)
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            VALUES (%s, %s, 1, %s, %s)
        """, (inv_id, f"Expense: {e_desc}", e_amt, e_amt))

    cur.execute("SELECT COALESCE(SUM(total), 0) FROM invoice_items WHERE invoice_id = %s", (inv_id,))
    subtotal = float(cur.fetchone()[0] or 0.0)

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings_dict = {r[0]: r[1] for r in cur.fetchall()}
    
    from services.tax_engine import TaxEngine
    tax_rate, tax_amt, final_total = TaxEngine.calculate_invoice_totals(settings_dict, subtotal)

    cur.execute("UPDATE invoices SET subtotal = %s, tax = %s, total = %s WHERE id = %s", (subtotal, tax_amt, final_total, inv_id))
    
    cur.execute("""
        INSERT INTO audit_logs (company_id, admin_email, action, target, details, ip_address, created_at)
        VALUES (%s, %s, 'INVOICE_CREATE', %s, %s, %s, CURRENT_TIMESTAMP)
    """, (comp_id, session.get('user_name', 'Office'), f"Invoice #{inv_ref}", f"Generated from Job #{job_ref} (Total: £{final_total:.2f})", request.remote_addr))
    
    conn.commit()
    flash(f"✅ Invoice #{inv_ref} generated successfully (£{final_total:.2f}).", "success")
    return redirect(f"/finance/invoice/{inv_id}/view")

    flash("✅ Assigned resources updated successfully.", "success")
    return redirect(f"/office/job/{job_id}/files")


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
        pass
        
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
            cur.execute("SELECT receipt_path FROM job_expenses WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if row and row[0]:
                from utils.validators import delete_file_safely
                delete_file_safely(row[0])
            cur.execute("DELETE FROM job_expenses WHERE id = %s", (item_id,))
            flash("🗑️ Expense/Receipt Deleted", "success")
        elif 'Photo' in item_type or 'Evidence' in item_type or 'Project' in item_type or 'Layout' in item_type or 'Building' in item_type or 'Certificate' in item_type or 'Other' in item_type:
            cur.execute("SELECT filepath FROM job_evidence WHERE id = %s", (item_id,))
            row = cur.fetchone()
            if row and row[0]:
                from utils.validators import delete_file_safely
                delete_file_safely(row[0])
            cur.execute("DELETE FROM job_evidence WHERE id = %s", (item_id,))
            flash("🗑️ Document Deleted", "success")
        elif 'Material' in item_type:
             cur.execute("DELETE FROM job_materials WHERE id = %s", (item_id,))
             flash("🗑️ Material Removed", "success")
        elif 'Timesheet' in item_type:
             cur.execute("DELETE FROM staff_timesheets WHERE id = %s", (item_id,))
             flash("🗑️ Logged Hours Removed", "success")
             
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        pass
        
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
            VALUES (%s, %s, %s, %s, %s, 'Pending')
        """, (session.get('company_id'), staff_id, job_id, hours, date_worked))
        
        conn.commit()
        flash(f"✅ Logged {hours} hours.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        pass
        
    return redirect(f"/office/job/{job_id}/files")
    
@jobs_bp.route('/office/job/<int:job_id>/upload-document', methods=['POST'])
def upload_job_document(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    doc_type = request.form.get('document_type')
    visible_to_client = True if request.form.get('visible_to_client') == '1' else False
    
    conn = get_db(); cur = conn.cursor()
    try:
        from utils.validators import save_secure_file
        
        if 'file' in request.files:
            file = request.files['file']
            db_path = save_secure_file(file, f"company_{comp_id}/job_evidence", f"JOB_{job_id}_")
            if db_path:
                cur.execute("""
                    INSERT INTO job_evidence (job_id, filepath, file_type, uploaded_by, visible_to_client) 
                    VALUES (%s, %s, %s, %s, %s)
                """, (job_id, db_path, doc_type, session['user_id'], visible_to_client))
                flash("📄 Document uploaded successfully.", "success")
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error uploading document: {e}", "error")
    finally:
        pass
        
    return redirect(request.referrer)

@jobs_bp.route('/office/job/save', methods=['POST'])
def save_job_action():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
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
        flash(f"✅ Job {ref} Created Successfully", "success")
        return redirect(f"/office/job/{new_job_id}/files")

@jobs_bp.route('/office/job/<int:job_id>/status', methods=['POST'])
def update_job_status(job_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    new_status = request.form.get('status')
    valid_statuses = ['Unscheduled', 'Scheduled', 'In Progress', 'Completed', 'Pending']
    if new_status in valid_statuses:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE jobs SET status = %s WHERE id = %s AND company_id = %s", (new_status, job_id, comp_id))
        conn.commit()
        flash(f"✅ Job status updated to {new_status}", "success")
    return redirect(f"/office/job/{job_id}/files")

@jobs_bp.route('/api/job/<int:job_id>/status', methods=['POST'])
def api_update_job_status(job_id):
    if 'user_id' not in session: return jsonify({'error': 'Unauthorized'}), 401
    comp_id = session.get('company_id')
    data = request.get_json(silent=True) or request.form
    new_status = data.get('status')
    valid_statuses = ['Unscheduled', 'Scheduled', 'In Progress', 'Completed', 'Pending']
    if new_status in valid_statuses:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE jobs SET status = %s WHERE id = %s AND company_id = %s", (new_status, job_id, comp_id))
        conn.commit()
        return jsonify({'success': True, 'status': new_status})
    return jsonify({'error': 'Invalid status'}), 400

