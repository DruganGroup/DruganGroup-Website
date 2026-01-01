from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.utils import secure_filename
import os
from datetime import date, datetime

site_bp = Blueprint('site', __name__)
UPLOAD_FOLDER = 'static/uploads/van_checks'
JOB_EVIDENCE_FOLDER = 'static/uploads/job_evidence'

# --- HELPER: CHECK ACCESS ---
def check_site_access():
    if 'user_id' not in session: return False
    return True

# --- HELPER: SELF-REPAIR DATABASE ---
def repair_site_tables(conn):
    try:
        cur = conn.cursor()
        cur.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS staff_id INTEGER")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS job_evidence (
                id SERIAL PRIMARY KEY,
                job_id INTEGER,
                filepath TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by INTEGER
            )
        """)
        conn.commit()
    except Exception as e:
        conn.rollback(); print(f"⚠️ Auto-Repair Warning: {e}")

# --- 1. SITE DASHBOARD ---
@site_bp.route('/site-hub')
@site_bp.route('/site-companion') 
def site_dashboard():
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    staff_id = session.get('user_id')
    conn = get_db(); repair_site_tables(conn); cur = conn.cursor()

    # Fetch "My Jobs"
    cur.execute("""
        SELECT j.id, j.status, j.ref, j.site_address, p.postcode, j.description, j.start_date
        FROM jobs j
        LEFT JOIN properties p ON j.site_address = p.address_line1 
        WHERE j.company_id = %s AND j.staff_id = %s AND j.status != 'Completed'
        ORDER BY j.start_date ASC
    """, (comp_id, staff_id))
    
    my_jobs = []
    for r in cur.fetchall():
        my_jobs.append({'id': r[0], 'status': r[1], 'reference': r[2], 'address': r[3], 'postcode': r[4] or '', 'notes': r[5]})

    config = get_site_config(comp_id); conn.close()
    
    return render_template('site/site_dashboard.html', 
                         staff_name=session.get('user_name'), 
                         my_jobs=my_jobs, 
                         brand_color=config['color'], 
                         logo_url=config['logo'])

# --- 2. DEDICATED VAN CHECK PAGE (New) ---
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
        
        # Handle Photo
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
                # If there are defects, mark as failed, otherwise Passed.
                is_safe = False if (defects and defects != "No Defects Reported") else True
                status_log = 'Check Failed' if not is_safe else 'Daily Check'
                
                # We combine the checklist confirmation into the description
                full_desc = f"Walkaround Complete. Signed by: {signature}. Mileage: {mileage}. Notes: {defects}"
                
                cur.execute("""
                    INSERT INTO maintenance_logs (company_id, vehicle_id, date, type, description, cost) 
                    VALUES (%s, %s, CURRENT_DATE, %s, %s, 0)
                """, (comp_id, v_id, status_log, full_desc))
                conn.commit()
                flash("✅ Safety Check Logged Successfully!")
                return redirect(url_for('site.site_dashboard'))
            else:
                flash("❌ Vehicle not found.")
        except Exception as e:
            conn.rollback(); flash(f"Error: {e}")

    # GET Request: Show form
    cur.execute("SELECT reg_plate FROM vehicles WHERE company_id = %s AND status='Active' ORDER BY reg_plate", (comp_id,))
    vehicles = [r[0] for r in cur.fetchall()]
    conn.close()

    return render_template('site/van_check_form.html', vehicles=vehicles)

# --- 3. VIEW SINGLE JOB ---
@site_bp.route('/site/job/<int:job_id>')
def view_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id'); conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.start_date, j.description, 
               c.name, c.phone, j.site_address, j.description
        FROM jobs j
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.id = %s AND j.company_id = %s
    """, (job_id, comp_id))
    job = cur.fetchone()

    cur.execute("SELECT filepath FROM job_evidence WHERE job_id = %s ORDER BY uploaded_at DESC", (job_id,))
    photos = [r[0] for r in cur.fetchall()]
    
    conn.close()
    if not job: return "Job not found", 404
    return render_template('site/job_details.html', job=job, photos=photos)

# --- 4. UPDATE JOB ---
@site_bp.route('/site/job/<int:job_id>/update', methods=['POST'])
def update_job(job_id):
    if not check_site_access(): return redirect(url_for('auth.login'))
    
    action = request.form.get('action')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        if action == 'start':
            cur.execute("UPDATE jobs SET status = 'In Progress' WHERE id = %s AND company_id = %s", (job_id, comp_id))
            flash("✅ Job Started - Timer Running")
        elif action == 'complete':
            cur.execute("UPDATE jobs SET status = 'Completed' WHERE id = %s AND company_id = %s", (job_id, comp_id))
            flash("🎉 Job Completed!")
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

# --- PUBLIC PAGES ---
@site_bp.route('/advertise')
@site_bp.route('/business-better')
def advertise_page(): return render_template('public/advert-bb.html')