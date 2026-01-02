from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.security import check_password_hash

portal_bp = Blueprint('portal', __name__)

# --- HELPER: CHECK PORTAL ACCESS ---
def check_portal_access():
    if 'portal_client_id' not in session: return False
    return True

# --- 1. LOGIN PAGE (The White Label Door) ---
@portal_bp.route('/portal/login/<int:company_id>', methods=['GET'])
def portal_login(company_id):
    # Fetch Company Branding so the login page looks like "Ace Plumbing"
    config = get_site_config(company_id)
    return render_template('portal/client_login.html', 
                         company_id=company_id,
                         company_name=config.get('name', 'Client Portal'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color', '#333333'))

# --- 2. AUTHENTICATION (Check Password) ---
@portal_bp.route('/portal/auth', methods=['POST'])
def portal_auth():
    company_id = request.form.get('company_id')
    email = request.form.get('email')
    password = request.form.get('password') # The new password field
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Fetch the stored HASH for this email and company
        cur.execute("SELECT id, name, password_hash FROM clients WHERE email = %s AND company_id = %s", (email, company_id))
        user = cur.fetchone()
        
        # Verify Password
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

# --- 3. PORTAL HOME (Dashboard) - FIXED ---
@portal_bp.route('/portal/home')
def portal_home():
    if not check_portal_access(): return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Active Jobs
    cur.execute("""
        SELECT id, ref, site_address, status, description 
        FROM jobs 
        WHERE client_id = %s AND status != 'Completed'
    """, (client_id,))
    active_jobs = [dict(zip(['id', 'ref', 'address', 'status', 'desc'], r)) for r in cur.fetchall()]
    
    # 2. Fetch Properties (MATCHING HTML INDICES)
    # Template expects: p[0]=ID, p[1]=Postcode, p[2]=Type, p[3]=Address, p[4]=Tenant
    cur.execute("""
        SELECT id, postcode, type, address_line1, tenant_name 
        FROM properties 
        WHERE client_id = %s
    """, (client_id,))
    properties = cur.fetchall() 
    
    # 3. Fetch Service Requests (MATCHING HTML INDICES)
    # Template expects: r[7]=Date, r[1]=Address, r[4]=Issue, r[5]=Severity, r[6]=Status
    # We use a JOIN to get the address (p.address_line1) into position 1
    cur.execute("""
        SELECT 
            sr.id,                  -- 0
            p.address_line1,        -- 1 (Address for display)
            sr.property_id,         -- 2
            sr.client_id,           -- 3
            sr.issue_description,   -- 4 (Issue)
            sr.severity,            -- 5 (Severity)
            sr.status,              -- 6 (Status)
            sr.created_at           -- 7 (Date)
        FROM service_requests sr
        LEFT JOIN properties p ON sr.property_id = p.id
        WHERE sr.client_id = %s
        ORDER BY sr.created_at DESC LIMIT 5
    """, (client_id,))
    requests = cur.fetchall()

    conn.close()
    
    return render_template('portal/portal_home.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         active_jobs=active_jobs,
                         properties=properties,
                         requests=requests)
                         
# --- 4. LOGOUT ---
@portal_bp.route('/portal/logout')
def portal_logout():
    # Only clear portal session
    session.pop('portal_client_id', None)
    return "Logged out. You can close this window."