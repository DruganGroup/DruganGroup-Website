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

# --- 3. PORTAL HOME (Production Version) ---
@portal_bp.route('/portal/home')
def portal_home():
    if not check_portal_access(): 
        return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Active Jobs
    # (Using empty list for now until we confirm the Jobs table structure, 
    # but this is where we will hook it up next)
    active_jobs = [] 
    
    # 2. Fetch Properties (Now requesting the REAL 'type' column)
    cur.execute("""
        SELECT id, postcode, type, address_line1, tenant_name 
        FROM properties 
        WHERE client_id = %s
    """, (client_id,))
    properties = cur.fetchall() 
    
    # 3. Fetch Service Requests
    # This will now work because Step 1 created the table
    cur.execute("""
        SELECT id, issue_description, status, created_at, severity
        FROM service_requests 
        WHERE client_id = %s 
        ORDER BY created_at DESC LIMIT 5
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
    # --- 4. MY INVOICES PAGE ---
@portal_bp.route('/portal/invoices')
def portal_invoices():
    if not check_portal_access(): return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Invoices (Adjust column names if yours differ)
    # We expect: id, invoice_number, date_issue, total_amount, status, file_path
    cur.execute("""
        SELECT id, invoice_number, date_issue, total_amount, status, file_path 
        FROM invoices 
        WHERE client_id = %s 
        ORDER BY date_issue DESC
    """, (client_id,))
    invoices = cur.fetchall()
    
    conn.close()
    
    return render_template('portal/portal_invoices.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         invoices=invoices)
                         
                         # --- 5. MY PROFILE (View & Update) ---
@portal_bp.route('/portal/profile', methods=['GET', 'POST'])
def portal_profile():
    if not check_portal_access(): return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        # Update Details
        new_name = request.form.get('name')
        new_email = request.form.get('email')
        new_password = request.form.get('password')
        
        try:
            # 1. Update Basic Info
            cur.execute("UPDATE clients SET name = %s, email = %s WHERE id = %s", (new_name, new_email, client_id))
            
            # 2. Update Password (only if typed)
            if new_password:
                hashed = generate_password_hash(new_password)
                cur.execute("UPDATE clients SET password_hash = %s WHERE id = %s", (hashed, client_id))
                
            conn.commit()
            flash("✅ Profile updated successfully!", "success")
            session['portal_client_name'] = new_name # Update session immediately
            
        except Exception as e:
            conn.rollback()
            flash(f"Error updating profile: {e}", "error")

    # Fetch current details to fill the form
    cur.execute("SELECT name, email FROM clients WHERE id = %s", (client_id,))
    client = cur.fetchone()
    conn.close()
    
    return render_template('portal/portal_profile.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         client=client)

# --- 6. ADD PROPERTY (Action) ---
@portal_bp.route('/portal/property/add', methods=['POST'])
def add_property():
    if not check_portal_access(): return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    # Get form data
    address = request.form.get('address')
    postcode = request.form.get('postcode')
    p_type = request.form.get('type') # e.g. Residential, Commercial
    tenant = request.form.get('tenant_name')

    conn = get_db(); cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, type, tenant_name)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, address, postcode, p_type, tenant))
        
        conn.commit()
        flash("✅ New property added to your list.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error adding property: {e}", "error")
    finally:
        conn.close()

    return redirect('/portal/home')