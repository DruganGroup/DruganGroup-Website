from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.security import check_password_hash, generate_password_hash
from services.enforcement import check_limit
from werkzeug.utils import secure_filename

portal_bp = Blueprint('portal', __name__)

# --- HELPER: CHECK PORTAL ACCESS ---
def check_portal_access():
    if 'portal_client_id' not in session: return False
    return True

# --- HELPER: GET LOGIN URL ---
def get_login_url():
    comp_id = session.get('portal_company_id', 1)
    return url_for('portal.portal_login', company_id=comp_id)

# --- 1. LOGIN PAGE ---
@portal_bp.route('/portal/login/<int:company_id>', methods=['GET'])
def portal_login(company_id):
    config = get_site_config(company_id)
    return render_template('portal/client_login.html', 
                         company_id=company_id,
                         company_name=config.get('name', 'Client Portal'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color', '#333333'))

# --- 2. AUTHENTICATION ---
@portal_bp.route('/portal/auth', methods=['POST'])
def portal_auth():
    company_id = request.form.get('company_id')
    email = request.form.get('email')
    password = request.form.get('password')
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        cur.execute("SELECT id, name, password_hash FROM clients WHERE email = %s AND company_id = %s", (email, company_id))
        user = cur.fetchone()
        
        if user and user[2] and check_password_hash(user[2], password):
            session['portal_client_id'] = user[0]
            session['portal_company_id'] = company_id
            session['portal_client_name'] = user[1]
            return redirect(url_for('portal.portal_home'))
        else:
            flash("❌ Invalid Email or Password.")
            return redirect(url_for('portal.portal_login', company_id=company_id))
    finally:
        conn.close()

# --- 3. PORTAL DASHBOARD (HOME) ---
@portal_bp.route('/portal/home')
def portal_home():
    if not check_portal_access(): return redirect(get_login_url())
    
    comp_id = session['portal_company_id']
    client_id = session['portal_client_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()

    # 1. Client Name
    cur.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
    res = cur.fetchone()
    client_name = res[0] if res else "Client"

    # 2. UPCOMING WORK (Live Schedule)
    # We fetch real details now, not just IDs
    cur.execute("""
        SELECT j.id, j.ref, j.description, j.start_date, j.status, p.address_line1
        FROM jobs j
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.client_id = %s 
        AND j.status IN ('Scheduled', 'In Progress', 'Pending')
        ORDER BY j.start_date ASC NULLS LAST
    """, (client_id,))
    active_jobs = cur.fetchall()
    
    # 3. Open Quotes Count
    cur.execute("SELECT COUNT(*) FROM quotes WHERE client_id = %s AND status IN ('Draft', 'Sent')", (client_id,))
    open_quotes = cur.fetchone()[0]

    # 4. Properties
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, p.type,
            (SELECT COUNT(*) FROM service_requests sr WHERE sr.property_id = p.id AND sr.status != 'Pending' AND sr.status != 'Completed')
        FROM properties p
        WHERE p.client_id = %s
    """, (client_id,))
    properties = cur.fetchall()

    # 5. Recent Requests
    cur.execute("""
        SELECT sr.id, p.address_line1, sr.issue_description, sr.status, sr.created_at, sr.severity
        FROM service_requests sr
        JOIN properties p ON sr.property_id = p.id
        WHERE sr.client_id = %s
        ORDER BY sr.created_at DESC LIMIT 5
    """, (client_id,))
    recent_requests = cur.fetchall()
    
    conn.close()
    
    return render_template('portal/portal_home.html', 
                         company_name=config.get('name'), 
                         client_name=client_name,
                         properties=properties,
                         active_jobs=active_jobs, # Now contains full data
                         open_quotes_count=open_quotes,
                         recent_requests=recent_requests,
                         brand_color=config.get('color'),
                         logo_url=config.get('logo'))

# --- 4. VIEW JOB (Photos Only - No Finance) ---
@portal_bp.route('/portal/job/<int:job_id>')
def portal_job_view(job_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Job (SECURITY: Must belong to Client)
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.description, j.start_date, j.end_date, 
               p.address_line1, p.postcode
        FROM jobs j
        LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s AND j.client_id = %s
    """, (job_id, client_id))
    job = cur.fetchone()
    
    if not job:
        conn.close(); return "Job not found or access denied", 404

    # 2. Fetch PHOTOS ONLY (Exclude Receipts/Expenses)
    # This query strictly looks at 'job_evidence' which is for site photos.
    # It does NOT look at 'job_expenses' or 'maintenance_logs'.
    cur.execute("""
        SELECT filepath, uploaded_at 
        FROM job_evidence 
        WHERE job_id = %s 
        ORDER BY uploaded_at DESC
    """, (job_id,))
    photos = cur.fetchall()
    
    conn.close()
    
    return render_template('portal/portal_job_view.html',
                         job=job,
                         photos=photos,
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'))

# --- 5. QUOTES & ACTIONS ---
@portal_bp.route('/portal/quotes')
def portal_quotes():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT id, reference, date, total, status 
        FROM quotes WHERE client_id = %s ORDER BY date DESC
    """, (client_id,))
    quotes = cur.fetchall()
    conn.close()
    
    return render_template('portal/portal_quotes.html',
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         quotes=quotes)

@portal_bp.route('/portal/quote/<int:quote_id>')
def quote_detail(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, reference, date, total, status FROM quotes WHERE id = %s AND client_id = %s", (quote_id, client_id))
    quote = cur.fetchone()
    
    if not quote: conn.close(); return "Quote not found", 404

    try:
        cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
        items = cur.fetchall()
    except: items = []
    conn.close()
    
    return render_template('portal/portal_quote_view.html', 
                           quote=quote, items=items,
                           company_name=config.get('name'),
                           brand_color=config.get('color'),
                           logo_url=config.get('logo'))

# --- NEW: ACCEPT / DECLINE QUOTE ---
@portal_bp.route('/portal/quote/<int:quote_id>/<action>')
def quote_action(quote_id, action):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    
    if action not in ['accept', 'decline']: return "Invalid action", 400
    
    new_status = 'Accepted' if action == 'accept' else 'Declined'
    
    conn = get_db(); cur = conn.cursor()
    try:
        # Security: Ensure Quote belongs to Client
        cur.execute("UPDATE quotes SET status = %s WHERE id = %s AND client_id = %s", (new_status, quote_id, client_id))
        conn.commit()
        
        flash(f"✅ Quote {new_status} successfully.", "success")
        if new_status == 'Accepted':
            flash("The office has been notified and will schedule your job shortly.", "info")
            
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('portal.portal_quotes'))

# --- 6. ADD PROPERTY ---
@portal_bp.route('/portal/property/add', methods=['POST'])
def add_property():
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    allowed, msg = check_limit(comp_id, 'max_properties')
    if not allowed:
        flash("❌ Limit Reached. Contact Office.", "error")
        return redirect('/portal/home')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, type, tenant_name, tenant_phone, key_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, request.form.get('address'), request.form.get('postcode'), 
              request.form.get('type'), request.form.get('tenant_name'), 
              request.form.get('tenant_phone'), request.form.get('key_code')))
        conn.commit(); flash("✅ Property added.", "success")
    except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")
    finally: conn.close()
    return redirect('/portal/home')

# --- 7. PROPERTY & JOB HISTORY ---
@portal_bp.route('/portal/property/<int:property_id>')
def property_detail(property_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Verify Access
    cur.execute("SELECT id, address_line1, postcode, type, tenant_name, tenant_phone, key_code FROM properties WHERE id = %s AND client_id = %s", (property_id, client_id))
    prop = cur.fetchone()
    if not prop: conn.close(); return redirect('/portal/home')

    # Fetch History
    cur.execute("SELECT id, ref, status, description, start_date FROM jobs WHERE property_id = %s ORDER BY start_date DESC", (property_id,))
    job_history = cur.fetchall()
    conn.close()
    
    return render_template('portal/portal_property_view.html',
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         prop=prop, job_history=job_history)

# --- 8. SERVICE REQUESTS ---
@portal_bp.route('/portal/request/submit', methods=['POST'])
def submit_request():
    if not check_portal_access(): return redirect(get_login_url())
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO service_requests (company_id, client_id, property_id, issue_description, severity, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'Pending', CURRENT_TIMESTAMP)
        """, (session['portal_company_id'], session['portal_client_id'], request.form.get('property_id'), 
              request.form.get('description'), request.form.get('severity')))
        conn.commit(); flash("✅ Fault reported.", "success")
    except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")
    finally: conn.close()
    return redirect(f"/portal/property/{request.form.get('property_id')}")

@portal_bp.route('/portal/request/<int:request_id>')
def request_detail(request_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT sr.id, sr.issue_description, sr.status, sr.created_at, sr.severity, p.address_line1, p.postcode, sr.property_id
        FROM service_requests sr JOIN properties p ON sr.property_id = p.id
        WHERE sr.id = %s AND sr.client_id = %s
    """, (request_id, client_id))
    req = cur.fetchone()
    
    completion = None
    if req and req[2] == 'Completed':
        cur.execute("""
            SELECT j.description, j.end_date, j.completion_photos, u.name 
            FROM jobs j LEFT JOIN users u ON j.engineer_id = u.id 
            WHERE j.property_id = %s AND j.status = 'Completed' ORDER BY j.end_date DESC LIMIT 1
        """, (req[7],))
        completion = cur.fetchone()
    
    conn.close()
    return render_template('portal/portal_request_view.html', req=req, completion=completion, company_name=config.get('name'), brand_color=config.get('color'), logo_url=config.get('logo'))

# --- 9. INVOICES & PROFILE ---
@portal_bp.route('/portal/invoices')
def portal_invoices():
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, reference, date, total, status FROM invoices WHERE client_id = %s ORDER BY date DESC", (client_id,))
    invoices = cur.fetchall()
    conn.close()
    
    return render_template('portal/portal_invoices.html', client_name=session.get('portal_client_name'), company_name=config.get('name'), logo_url=config.get('logo'), brand_color=config.get('color'), invoices=invoices)

@portal_bp.route('/portal/profile', methods=['GET', 'POST'])
def portal_profile():
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        try:
            cur.execute("UPDATE clients SET name=%s, email=%s, phone=%s WHERE id=%s", (request.form.get('name'), request.form.get('email'), request.form.get('phone'), client_id))
            if request.form.get('new_password'):
                if request.form.get('new_password') == request.form.get('confirm_password'):
                    cur.execute("UPDATE clients SET password_hash=%s WHERE id=%s", (generate_password_hash(request.form.get('new_password')), client_id))
            conn.commit(); flash("✅ Profile updated.", "success")
        except Exception as e: conn.rollback(); flash(f"Error: {e}", "error")

    cur.execute("SELECT id, name, email, phone FROM clients WHERE id = %s", (client_id,))
    client = cur.fetchone()
    conn.close()
    return render_template('portal/portal_profile.html', client=client, company_name=config.get('name'), brand_color=config.get('color'), logo_url=config.get('logo'))

# --- 10. LOGOUT ---
@portal_bp.route('/portal/logout')
def portal_logout():
    comp_id = session.get('portal_company_id', 1)
    session.clear()
    return redirect(url_for('portal.portal_login', company_id=comp_id))