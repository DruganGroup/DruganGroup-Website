from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.utils import secure_filename
import os
from datetime import datetime, timedelta, date

# Try importing AI, but don't crash if it fails
try:
    from services.ai_assistant import scan_receipt
except ImportError:
    scan_receipt = None 

site_bp = Blueprint('site', __name__)
UPLOAD_FOLDER = 'static/uploads/van_checks'
JOB_EVIDENCE_FOLDER = 'static/uploads/job_evidence'

# --- HELPER: CHECK ACCESS ---
def check_site_access():
    if 'user_id' not in session: return False
    return True

# --- HELPER: GET STAFF IDENTITY ---
def get_staff_identity(user_id, cur):
    """
    Robustly finds the Staff ID for the current logged-in user.
    """
    # 1. Try to find matching Staff record via Email linking
    cur.execute("""
        SELECT s.id, s.name, u.company_id 
        FROM users u
        JOIN staff s ON LOWER(u.email) = LOWER(s.email) AND u.company_id = s.company_id
        WHERE u.id = %s
    """, (user_id,))
    match = cur.fetchone()
    
    if match: return match[0], match[1], match[2]
    
    # 2. Fallback: Just return User info if no Staff link found
    cur.execute("SELECT company_id, name, username FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    if user: return None, (user[1] or user[2]), user[0]
    return None, "Unknown", None

# --- 1. SITE HUB DASHBOARD (7-Day Calendar & Clock Fix) ---
@site_bp.route('/site-hub')
@site_bp.route('/site-companion')
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # Use the helper to guarantee we find the same ID as the clock-in route
    staff_id, _, _ = get_staff_identity(session['user_id'], cur)
    
    # A. CLOCK STATUS CHECK
    is_clocked_in = False
    if staff_id:
        # Check for any open shift for this staff member
        cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        is_clocked_in = cur.fetchone() is not None
    
    # B. 7-DAY CALENDAR SCHEDULE
    jobs = []
    if staff_id:
        # Note the ::DATE cast to fix the previous "text >= date" crash
        cur.execute("""
            SELECT j.id, j.ref, j.site_address, c.name, j.description, j.start_date, j.status 
            FROM jobs j 
            LEFT JOIN clients c ON j.client_id = c.id 
            WHERE j.engineer_id = %s 
            AND j.status != 'Completed'
            AND j.start_date::DATE >= CURRENT_DATE 
            AND j.start_date::DATE <= CURRENT_DATE + INTERVAL '7 days'
            ORDER BY j.start_date ASC
        """, (staff_id,))
        jobs = cur.fetchall()
    
    conn.close()
    return render_template('site/site_dashboard.html', jobs=jobs, is_clocked_in=is_clocked_in)

# --- 2. CLOCK IN ---
@site_bp.route('/site/clock-in', methods=['POST'])
def clock_in():
    if 'user_id' not in session: return redirect('/login')
    conn = get_db(); cur = conn.cursor()
    
    staff_id, _, comp_id = get_staff_identity(session['user_id'], cur)
    
    if not staff_id:
        flash("❌ Error: Your user is not linked to a Staff Profile. Please contact Office.", "error")
        return redirect('/site-hub')

    try:
        cur.execute("SELECT id FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        if cur.fetchone():
            flash("⚠️ You are already clocked in.", "warning")
        else:
            cur.execute("INSERT INTO staff_timesheets (staff_id, company_id, clock_in, date) VALUES (%s, %s, CURRENT_TIMESTAMP, CURRENT_DATE)", (staff_id, comp_id))
            conn.commit()
            flash("🕒 Clocked In Successfully!")
    except Exception as e: 
        conn.rollback()
        flash(f"Error: {e}")
    finally: 
        conn.close()
    return redirect('/site-hub')

# --- 3. CLOCK OUT ---
@site_bp.route('/site/clock-out', methods=['POST'])
def clock_out():
    if 'user_id' not in session: return redirect('/login')
    conn = get_db(); cur = conn.cursor()
    
    staff_id, _, _ = get_staff_identity(session['user_id'], cur)

    try:
        cur.execute("SELECT id, clock_in FROM staff_timesheets WHERE staff_id = %s AND clock_out IS NULL ORDER BY id DESC LIMIT 1", (staff_id,))
        row = cur.fetchone()
        if row:
            sheet_id = row[0]; start_time = row[1]
            
            # Calc hours
            diff = datetime.now() - start_time
            hours = diff.total_seconds() / 3600
            
            cur.execute("UPDATE staff_timesheets SET clock_out = CURRENT_TIMESTAMP, total_hours = %s WHERE id = %s", (round(hours, 2), sheet_id))
            conn.commit()
            flash(f"🕒 Clocked Out. Shift: {round(hours, 2)} hrs.")
        else:
            flash("⚠️ No active shift found to stop.", "warning")
    except Exception as e: 
        conn.rollback()
        flash(f"Error: {e}")
    finally: 
        conn.close()
    return redirect('/site-hub')

# --- 4. FUEL LOG (Protected against AI Import Errors) ---
@site_bp.route('/site/log-fuel', methods=['GET', 'POST'])
def log_fuel():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    staff_id, _, _ = get_staff_identity(session['user_id'], cur)
    search_id = staff_id if staff_id else session['user_id']

    # Find Van
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE assigned_driver_id = %s", (search_id,))
    vehicle = cur.fetchone()

    if not vehicle:
        flash("❌ No vehicle assigned to you.")
        return redirect(url_for('site.site_dashboard'))
    
    v_id, v_reg = vehicle

    if request.method == 'POST':
        file = request.files.get('receipt')
        if file and file.filename != '':
            try:
                filename = secure_filename(f"FUEL_{v_reg}_{int(datetime.now().timestamp())}_{file.filename}")
                full_path = os.path.join(UPLOAD_FOLDER, filename)
                os.makedirs(UPLOAD_FOLDER, exist_ok=True) 
                file.save(full_path)
                db_path = f"uploads/van_checks/{filename}"

                cost = 0.0
                desc = f"Fuel for {v_reg}"
                
                # AI Scan (Try/Except to prevent 502 crashes)
                if scan_receipt:
                    try:
                        scan = scan_receipt(full_path)
                        if scan['success']:
                            data = scan['data']
                            cost = float(data.get('total_cost', 0))
                            if data.get('vendor'): desc = f"Fuel: {data.get('vendor')} ({v_reg})"
                            flash(f"✨ Receipt Scanned: £{cost}")
                    except Exception as ai_error:
                        print(f"AI Error: {ai_error}") 
                        flash("⚠️ AI failed to read receipt, please verify amount.")

                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost, receipt_path) 
                    VALUES (%s, %s, CURRENT_DATE, 'Fuel', %s, %s, %s)
                """, (comp_id, v_id, desc, cost, db_path))
                
                conn.commit()
                return redirect(url_for('site.site_dashboard'))
            except Exception as e:
                conn.rollback()
                flash(f"Error saving log: {e}")

    return render_template('site/fuel_form.html', reg=v_reg)

# --- 5. JOB DETAILS ---
@site_bp.route('/site/job/<int:job_id>')
def view_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.start_date, j.description, c.name, c.phone, j.site_address, j.description, j.id
        FROM jobs j LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    job = cur.fetchone()
    cur.execute("SELECT filepath FROM job_evidence WHERE job_id = %s ORDER BY uploaded_at DESC", (job_id,))
    photos = [r[0] for r in cur.fetchall()]
    conn.close()
    if not job: return "Job not found", 404
    return render_template('site/job_details.html', job=job, photos=photos)

# --- 6. UPDATE JOB (With Manual Notes/Draft Invoice) ---
@site_bp.route('/site/job/<int:job_id>/update', methods=['POST'])
def update_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    action = request.form.get('action')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    try:
        if action == 'start':
            cur.execute("UPDATE jobs SET status = 'In Progress', start_date = CURRENT_TIMESTAMP WHERE id = %s", (job_id,))
            flash("🚀 Job Started.")
        
        elif action == 'complete':
            signature = request.form.get('signature')
            work_summary = request.form.get('work_summary')
            private_notes = request.form.get('private_notes')
            
            cur.execute("SELECT client_id, ref, description, start_date, property_id FROM jobs WHERE id = %s", (job_id,))
            client_id, job_ref, job_desc, job_date, prop_id = cur.fetchone()
            clean_ref = job_ref.replace("Ref: ", "").replace("Quote Work: ", "").strip()

            cur.execute("UPDATE jobs SET status = 'Completed', end_date = CURRENT_TIMESTAMP, work_summary = %s, private_notes = %s WHERE id = %s", (work_summary, private_notes, job_id))

            cur.execute("SELECT id FROM quotes WHERE reference = %s AND company_id = %s", (clean_ref, comp_id))
            quote_row = cur.fetchone()
            
            cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id = %s", (comp_id,))
            inv_ref = f"INV-{1000 + cur.fetchone()[0] + 1}"

            if quote_row:
                cur.execute("""
                    INSERT INTO invoices (company_id, client_id, quote_ref, reference, date, due_date, status, subtotal, tax, total, notes) 
                    VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + 14, 'Unpaid', 0, 0, 0, %s) 
                    RETURNING id
                """, (comp_id, client_id, clean_ref, inv_ref, f"Job Signed by: {signature}"))
                inv_id = cur.fetchone()[0]
                
                cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_row[0],))
                items = cur.fetchall()
                subtotal = 0.0
                for item in items:
                    cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, %s, %s, %s, %s)", (inv_id, item[0], item[1], item[2], item[3]))
                    subtotal += float(item[3])
                
                tax = subtotal * 0.20 
                total = subtotal + tax
                cur.execute("UPDATE invoices SET subtotal=%s, tax=%s, total=%s WHERE id=%s", (subtotal, tax, total, inv_id)) 
                flash(f"🎉 Quoted Invoice {inv_ref} Generated.")
            else:
                cur.execute("INSERT INTO invoices (company_id, client_id, reference, date, due_date, status, subtotal, tax, total, notes) VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE+14, 'Draft', 0, 0, 0, %s) RETURNING id", (comp_id, client_id, inv_ref, "Pending Pricing"))
                inv_id = cur.fetchone()[0]
                cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) VALUES (%s, 'Details to Follow', 1, 0, 0)", (inv_id,))
                flash(f"✅ Draft Invoice {inv_ref} sent to Office.")

            cur.execute("UPDATE service_requests SET status = 'Completed' WHERE property_id = %s AND status = 'In Progress'", (prop_id,))

        elif action == 'upload_photo':
            if 'photo' in request.files:
                file = request.files['photo']
                if file.filename != '':
                    os.makedirs(JOB_EVIDENCE_FOLDER, exist_ok=True)
                    filename = secure_filename(f"JOB_{job_id}_{int(datetime.now().timestamp())}_{file.filename}")
                    db_path = f"uploads/job_evidence/{filename}"
                    file.save(os.path.join(JOB_EVIDENCE_FOLDER, filename))
                    cur.execute("INSERT INTO job_evidence (job_id, filepath, uploaded_by) VALUES (%s, %s, %s)", (job_id, db_path, session['user_id']))
                    flash("📷 Photo Uploaded")

        conn.commit()
    except Exception as e: conn.rollback(); flash(f"Error: {e}")
    finally: conn.close()
    if action == 'complete': return redirect(url_for('site.site_dashboard'))
    return redirect(url_for('site.view_job', job_id=job_id))
    
# --- 7. VAN CHECK PAGE ---
@site_bp.route('/site/van-check', methods=['GET', 'POST'])
def van_check_page():
    if not check_site_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        reg = request.form.get('reg_plate')
        mileage = request.form.get('mileage')
        defects = request.form.get('defects') or "No Defects Reported"
        signature = request.form.get('signature')
        
        try:
            cur.execute("SELECT id FROM vehicles WHERE reg_plate = %s", (reg,))
            v_row = cur.fetchone()
            if v_row:
                v_id = v_row[0]
                is_safe = False if (defects and defects != "No Defects Reported") else True
                status_log = 'Check Failed' if not is_safe else 'Daily Check'
                full_desc = f"Walkaround Complete. Signed: {signature}. Mileage: {mileage}. Notes: {defects}"
                
                cur.execute("INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost) VALUES (%s, %s, CURRENT_DATE, %s, %s, 0)", (comp_id, v_id, status_log, full_desc))
                conn.commit()
                flash("✅ Safety Check Logged!")
                return redirect(url_for('site.site_dashboard'))
            else:
                flash("❌ Vehicle not found.")
        except Exception as e: conn.rollback(); flash(f"Error: {e}")

    cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate", (comp_id,))
    vehicles = [r[0] for r in cur.fetchall()]
    conn.close()
    return render_template('site/van_check_form.html', vehicles=vehicles)