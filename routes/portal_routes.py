from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

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

# --- 6. ADD PROPERTY (Professional Version) ---
@portal_bp.route('/portal/property/add', methods=['POST'])
def add_property():
    if not check_portal_access(): return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    # Get form data
    address = request.form.get('address')
    postcode = request.form.get('postcode')
    p_type = request.form.get('type')
    
    # New Details
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
    if not check_portal_access(): return redirect(url_for('portal.portal_login', company_id=session.get('portal_company_id')))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Property Details (including the new fields)
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

    # 2. Fetch Job History for this specific property
    cur.execute("""
        SELECT id, ref, status, description, created_at 
        FROM jobs 
        WHERE property_id = %s 
        ORDER BY created_at DESC
    """, (property_id,))
    job_history = cur.fetchall()

    conn.close()
    
    return render_template('portal/portal_property_view.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         prop=prop,
                         job_history=job_history)
                         
 # --- 8. SUBMIT SERVICE REQUEST ---
@portal_bp.route('/portal/request/submit', methods=['POST'])
def submit_request():
    if not check_portal_access(): return redirect(url_for('portal.portal_login'))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    property_id = request.form.get('property_id')
    description = request.form.get('description')
    severity = request.form.get('severity', 'Low')
    
    # Handle Image Upload
    image_url = None
    file = request.files.get('image')
    if file and file.filename != '':
        filename = secure_filename(f"req_{client_id}_{file.filename}")
        upload_path = os.path.join('static/uploads/requests', filename)
        # Ensure directory exists
        os.makedirs('static/uploads/requests', exist_ok=True)
        file.save(upload_path)
        image_url = f"/static/uploads/requests/{filename}"

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO service_requests (client_id, property_id, issue_description, severity, image_url, status)
            VALUES (%s, %s, %s, %s, %s, 'Open')
        """, (client_id, property_id, description, severity, image_url))
        conn.commit()
        flash("✅ Maintenance request submitted. We will contact you shortly.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()

    return redirect('/portal/home')
    # --- 9. MY QUOTES PAGE ---
@portal_bp.route('/portal/quotes')
def portal_quotes():
    if not check_portal_access(): return redirect(url_for('portal.portal_login'))
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Quotes for this client
    # We expect columns: id, reference, date, total, status
    try:
        cur.execute("""
            SELECT id, reference, date, total, status 
            FROM quotes 
            WHERE client_id = %s 
            ORDER BY date DESC
        """, (client_id,))
        quotes = cur.fetchall()
    except Exception as e:
        # If table doesn't exist yet, just return empty list to prevent crash
        quotes = []
        print(f"Quotes Error: {e}")
        
    conn.close()
    
    return render_template('portal/portal_quotes.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         quotes=quotes)