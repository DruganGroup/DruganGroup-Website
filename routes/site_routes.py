from flask import Blueprint, render_template, session, redirect, url_for
from db import get_db, get_site_config

site_bp = Blueprint('site', __name__)

@site_bp.route('/site-hub')
def site_dashboard():
    if not session.get('user_id'): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # 1. Get Stats
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status = 'Pending'", (comp_id,))
    pending_count = cur.fetchone()[0]
    
    # (Assuming you have a 'jobs' table, if not, we use service_requests as a placeholder for now)
    # If tables don't exist yet, these try/except blocks prevent crashing
    active_jobs = 0
    try:
        cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id = %s AND status = 'Active'", (comp_id,))
        active_jobs = cur.fetchone()[0]
    except: pass

    active_gangs = 0
    try:
        cur.execute("SELECT COUNT(*) FROM staff WHERE company_id = %s AND role = 'Site Manager'", (comp_id,))
        active_gangs = cur.fetchone()[0]
    except: pass

    # 2. Get Recent List
    recent_jobs = []
    try:
        # Fetch actual jobs if table exists
        cur.execute("""
            SELECT id, reference, address, postcode, status, assigned_gang 
            FROM jobs WHERE company_id = %s ORDER BY start_date DESC LIMIT 5
        """, (comp_id,))
        rows = cur.fetchall()
        for r in rows:
            recent_jobs.append({
                'id': r[0], 'reference': r[1], 'address': r[2], 
                'postcode': r[3], 'status': r[4], 'gang_name': r[5]
            })
    except:
        pass # Return empty list if table not ready

    conn.close()
    
    return render_template('site/site_dashboard.html',
                           brand_color=config['color'],
                           logo_url=config['logo'],
                           active_jobs_count=active_jobs,
                           pending_req_count=pending_count,
                           active_gangs_count=active_gangs,
                           recent_jobs=recent_jobs)