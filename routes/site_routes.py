from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.utils import secure_filename
import os
from datetime import date

site_bp = Blueprint('site', __name__)
UPLOAD_FOLDER = 'static/uploads/van_checks'

# --- HELPER: CHECK ACCESS ---
def check_site_access():
    if 'user_id' not in session: return False
    return True

# --- HELPER: SELF-REPAIR DATABASE ---
def repair_jobs_table_if_needed(conn):
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS staff_id INTEGER")
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Auto-Repair Warning: {e}")

# --- 1. SITE DASHBOARD (WORKER VIEW) ---
@site_bp.route('/site-hub', methods=['GET', 'POST'])
@site_bp.route('/site-companion', methods=['GET', 'POST']) 
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    staff_id = session.get('user_id')
    
    conn = get_db()
    
    # 1. RUN AUTO-REPAIR
    repair_jobs_table_if_needed(conn)
    
    cur = conn.cursor()

    # --- HANDLE VAN CHECK SUBMISSION ---
    if request.method == 'POST' and request.form.get('action') == 'van_check':
        reg = request.form.get('reg_plate')
        mileage = request.form.get('mileage')
        safe = request.form.get('is_safe')
        defects = request.form.get('defects')
        
        filename = None
        if 'photo' in request.files:
            file = request.files['photo']
            if file.filename != '':
                os.makedirs(UPLOAD_FOLDER, exist_ok=True)
                filename = secure_filename(f"{date.today()}_{reg}_{file.filename}")
                file.save(os.path.join(UPLOAD_FOLDER, filename))

        try:
            cur.execute("SELECT id FROM vehicles WHERE reg_plate = %s", (reg,))
            v_row = cur.fetchone()
            if v_row:
                v_id = v_row[0]
                desc = f"Daily Check: {safe.upper()}. Mileage: {mileage}. Notes: {defects}"
                status_log = 'Check Failed' if safe == 'no' else 'Daily Check'
                
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost) 
                    VALUES (%s, %s, CURRENT_DATE, %s, %s, 0)
                """, (comp_id, v_id, status_log, desc))
                conn.commit()
                flash("✅ Van Check Submitted!")
            else:
                flash("❌ Vehicle not found.")
        except Exception as e:
            conn.rollback(); flash(f"Error: {e}")

    # --- LOAD DASHBOARD DATA ---
    cur.execute("""
        SELECT j.id, j.status, j.ref, j.site_address, p.postcode, j.description, j.start_date
        FROM jobs j
        LEFT JOIN properties p ON j.site_address = p.address_line1 
        WHERE j.company_id = %s AND j.staff_id = %s AND j.status != 'Completed'
        ORDER BY j.start_date ASC
    """, (comp_id, staff_id))
    
    my_jobs = []
    for r in cur.fetchall():
        my_jobs.append({
            'id': r[0], 'status': r[1], 'reference': r[2], 
            'address': r[3], 'postcode': r[4] or '', 'notes': r[5]
        })

    cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate", (comp_id,))
    vehicles = [r[0] for r in cur.fetchall()]
    
    config = get_site_config(comp_id)
    conn.close()
    
    # FIX: Point to the 'site/' subfolder
    return render_template('site/site_dashboard.html', 
                         staff_name=session.get('user_name'), 
                         my_jobs=my_jobs, 
                         vehicles=vehicles,
                         brand_color=config['color'], 
                         logo_url=config['logo'])

# --- 2. VIEW SINGLE JOB ---
@site_bp.route('/site/job/<int:job_id>')
def view_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.start_date, j.description, 
               c.name, c.phone, j.site_address, j.description
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    
    job = cur.fetchone()
    conn.close()
    
    if not job: return "Job not found", 404
    
    # FIX: Point to the 'site/' subfolder
    return render_template('site/job_details.html', job=job)

# --- 3. PUBLIC PAGES ---
@site_bp.route('/advertise')
@site_bp.route('/business-better')
def advertise_page():
    return render_template('public/advert-bb.html')