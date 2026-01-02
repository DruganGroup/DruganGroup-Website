from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

portal_bp = Blueprint('portal', __name__)

# --- HELPER: CHECK PORTAL ACCESS ---
def check_portal_access():
    if 'portal_client_id' not in session: return False
    return True

# --- HELPER: GET LOGIN URL (Safe Fallback) ---
def get_login_url():
    # If session has no company_id, default to 1 to prevent crash
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
    conn = get_db(); cur = conn.cursor()
    
    # 1. GET COMPANY NAME
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'company_name'", (comp_id,))
    row_name = cur.fetchone()
    company_name = row_name[0] if row_name else "Client Portal"
    session['portal_company_name'] = company_name

    # 2. Get Client Name
    cur.execute("SELECT name FROM clients WHERE id = %s", (client_id,))
    res = cur.fetchone()
    client_name = res[0] if res else "Client"

    # 3. Stats: Active Jobs
    cur.execute("SELECT id FROM jobs WHERE client_id = %s AND status != 'Completed'", (client_id,))
    active_jobs = cur.fetchall()
    
    # 4. Stats: Open Quotes
    cur.execute("SELECT COUNT(*) FROM quotes WHERE client_id = %s AND status IN ('Draft', 'Sent')", (client_id,))
    open_quotes = cur.fetchone()[0]

    # 5. Fetch Properties with Issue Count
    cur.execute("""
        SELECT 
            p.id, 
            p.address_line1, 
            p.postcode, 
            p.type,
            (SELECT COUNT(*) FROM service_requests sr WHERE sr.property_id = p.id AND sr.status != 'Pending' AND sr.status != 'Completed') as open_issues
        FROM properties p
        WHERE p.client_id = %s
    """, (client_id,))
    properties = cur.fetchall()

    # 6. Recent Requests
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
                         company_name=company_name, 
                         client_name=client_name,
                         properties=properties,
                         active_jobs=active_jobs,
                         open_quotes_count=open_quotes,
                         recent_requests=recent_requests,
                         brand_color=session.get('portal_brand_color'),
                         logo_url=session.get('portal_logo_url'))

# --- 4. LOGOUT ---
@portal_bp.route('/portal/logout')
def portal_logout():
    # Capture company ID before clearing session for redirect
    comp_id = session.get('portal_company_id', 1)
    session.pop('portal_client_id', None)
    return redirect(url_for('portal.portal_login', company_id=comp_id))

# --- 5. MY INVOICES PAGE ---
@portal_bp.route('/portal/invoices')
def portal_invoices():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT id, invoice_number, date_issue, total_amount, status, file_path 
        FROM invoices 
        WHERE client_id = %s 
        ORDER BY date_issue DESC
    """, (client_id,))
    invoices = cur.fetchall()
    conn.close()
    
    return render_template('portal/portal_invoices.html',
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         invoices=invoices)

# --- 6. ADD PROPERTY ---
@portal_bp.route('/portal/property/add', methods=['POST'])
def add_property():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    address = request.form.get('address')
    postcode = request.form.get('postcode')
    p_type = request.form.get('type')
    tenant_name = request.form.get('tenant_name')
    tenant_phone = request.form.get('tenant_phone')
    key_code = request.form.get('key_code')

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties 
            (company_id, client_id, address_line1, postcode, type, tenant_name, tenant_phone, key_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, address, postcode, p_type, tenant_name, tenant_phone, key_code))
        conn.commit()
        flash("✅ Property added successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error adding property: {e}", "error")
    finally:
        conn.close()

    return redirect('/portal/home')

# --- 7. PROPERTY DETAIL VIEW ---
@portal_bp.route('/portal/property/<int:property_id>')
def property_detail(property_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Property
    cur.execute("""
        SELECT id, address_line1, postcode, type, tenant_name, tenant_phone, key_code 
        FROM properties 
        WHERE id = %s AND client_id = %s
    """, (property_id, client_id))
    prop = cur.fetchone()
    
    if not prop:
        conn.close()
        flash("Property not found or access denied.", "error")
        return redirect('/portal/home')

    # Fetch Job History
    cur.execute("""
        SELECT id, ref, status, description, start_date 
        FROM jobs 
        WHERE property_id = %s 
        ORDER BY start_date DESC
    """, (property_id,))
    job_history = cur.fetchall()

    conn.close()
    
    return render_template('portal/portal_property_view.html',
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         prop=prop,
                         job_history=job_history)

# --- 8. SUBMIT SERVICE REQUEST ---
@portal_bp.route('/portal/request/submit', methods=['POST'])
def submit_request():
    if not check_portal_access(): return redirect(get_login_url())
    
    prop_id = request.form.get('property_id')
    desc = request.form.get('description')
    severity = request.form.get('severity')
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO service_requests (company_id, client_id, property_id, issue_description, severity, status, created_at)
            VALUES (%s, %s, %s, %s, %s, 'Pending', CURRENT_TIMESTAMP)
        """, (comp_id, client_id, prop_id, desc, severity))
        conn.commit()
        flash("✅ Fault reported successfully. The Service Desk has been notified.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error reporting fault: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('portal.property_detail', property_id=prop_id))

# --- 9. VIEW REQUEST DETAILS (With Photos & Engineer) ---
@portal_bp.route('/portal/request/<int:request_id>')
def request_detail(request_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Request
    cur.execute("""
        SELECT sr.id, sr.issue_description, sr.status, sr.created_at, sr.severity, 
               p.address_line1, p.postcode, sr.property_id
        FROM service_requests sr
        JOIN properties p ON sr.property_id = p.id
        WHERE sr.id = %s AND sr.client_id = %s
    """, (request_id, client_id))
    req = cur.fetchone()
    
    if not req:
        conn.close()
        return "Request not found", 404

    # 2. Fetch Completion Details (The Job)
    completion_details = None
    if req[2] == 'Completed':
        cur.execute("""
            SELECT j.description, j.end_date, j.completion_photos, 
                   u.name as engineer_name
            FROM jobs j
            LEFT JOIN users u ON j.engineer_id = u.id
            WHERE j.property_id = %s AND j.status = 'Completed'
            ORDER BY j.end_date DESC LIMIT 1
        """, (req[7],)) 
        completion_details = cur.fetchone()

    conn.close()
    
    return render_template('portal/portal_request_view.html', 
                         req=req, 
                         completion=completion_details,
                         company_name=session.get('portal_company_name'),
                         brand_color=session.get('portal_brand_color'))

# --- 10. MY QUOTES PAGE ---
@portal_bp.route('/portal/quotes')
def portal_quotes():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, reference, date, total, status 
            FROM quotes 
            WHERE client_id = %s 
            ORDER BY date DESC
        """, (client_id,))
        quotes = cur.fetchall()
    except Exception as e:
        quotes = []
        
    conn.close()
    
    return render_template('portal/portal_quotes.html',
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         quotes=quotes)

# --- 11. QUOTE DETAILS & ACTIONS ---
@portal_bp.route('/portal/quote/<int:quote_id>')
def quote_detail(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("SELECT id, reference, date, total, status FROM quotes WHERE id = %s AND client_id = %s", (quote_id, client_id))
    quote = cur.fetchone()
    
    if not quote:
        conn.close()
        return "Quote not found or access denied", 404

    items = []
    try:
        cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
        items = cur.fetchall()
    except: pass 

    conn.close()
    return render_template('portal/portal_quote_view.html', quote=quote, items=items)

@portal_bp.route('/portal/quote/<int:quote_id>/accept')
def quote_accept(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s AND client_id = %s", (quote_id, session['portal_client_id']))
    conn.commit(); conn.close()
    flash("✅ Quote Accepted!", "success")
    return redirect(url_for('portal.quote_detail', quote_id=quote_id))

@portal_bp.route('/portal/quote/<int:quote_id>/decline')
def quote_decline(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE quotes SET status = 'Declined' WHERE id = %s AND client_id = %s", (quote_id, session['portal_client_id']))
    conn.commit(); conn.close()
    flash("❌ Quote Declined.", "warning")
    return redirect(url_for('portal.quote_detail', quote_id=quote_id))

# --- 12. PROFILE MANAGEMENT ---
@portal_bp.route('/portal/profile', methods=['GET', 'POST'])
def portal_profile():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')

        try:
            # 1. Update Basic Info
            cur.execute("UPDATE clients SET name=%s, email=%s, phone=%s WHERE id=%s", (name, email, phone, client_id))
            
            # 2. Update Password (only if user typed something)
            msg = "✅ Profile updated successfully."
            if new_pass:
                if new_pass == confirm_pass:
                    hashed_pw = generate_password_hash(new_pass)
                    cur.execute("UPDATE clients SET password_hash=%s WHERE id=%s", (hashed_pw, client_id))
                    msg = "✅ Profile & Password updated successfully."
                else:
                    flash("❌ Passwords did not match. Profile updated, but password kept same.", "error")

            conn.commit()
            flash(msg, "success")
            
        except Exception as e:
            conn.rollback()
            flash(f"Error updating profile: {e}", "error")

    # Fetch Client Data
    cur.execute("SELECT id, name, email, phone FROM clients WHERE id = %s", (client_id,))
    client = cur.fetchone()
    conn.close()

    return render_template('portal/portal_profile.html', 
                         client=client,
                         company_name=session.get('portal_company_name'),
                         brand_color=session.get('portal_brand_color'))