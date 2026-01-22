from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.security import check_password_hash, generate_password_hash
from services.enforcement import check_limit
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date

portal_bp = Blueprint('portal', __name__)

# --- HELPER: CHECK ACCESS ---
def check_portal_access():
    if 'portal_client_id' not in session: return False
    return True

# --- HELPER: LOGIN URL ---
def get_login_url():
    comp_id = session.get('portal_company_id', 1)
    return url_for('portal.portal_login', company_id=comp_id)

# --- HELPER: DATE FORMATTER ---
def format_date_by_country(date_val, comp_id):
    if not date_val: return None # Return None so template handles blank
    dt_obj = date_val
    if isinstance(date_val, str):
        try: dt_obj = datetime.strptime(date_val, '%Y-%m-%d')
        except: return date_val
    
    config = get_site_config(comp_id)
    if config.get('country') == 'United States': return dt_obj.strftime('%m/%d/%Y')
    return dt_obj.strftime('%d/%m/%Y')

# --- HELPER: COMPLIANCE STATUS CHECKER ---
def get_compliance_status(expiry_date):
    if not expiry_date: return None # Don't return status if no date
    
    today = date.today()
    if isinstance(expiry_date, str): 
        try: expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()
        except: return None

    if isinstance(expiry_date, datetime): expiry_date = expiry_date.date()

    delta = (expiry_date - today).days

    if delta < 0: return {'status': 'Expired', 'class': 'danger', 'label': 'Expired', 'days': delta}
    if delta < 30: return {'status': 'Expiring', 'class': 'warning text-dark', 'label': 'Expiring Soon', 'days': delta}
    return {'status': 'Valid', 'class': 'success', 'label': 'Valid', 'days': delta}

# --- 1. LOGIN ---
@portal_bp.route('/portal/login/<int:company_id>')
def portal_login(company_id):
    config = get_site_config(company_id)
    return render_template('portal/client_login.html', company_id=company_id, 
                         company_name=config.get('name'), logo_url=config.get('logo'), 
                         brand_color=config.get('color', '#333333'))

# --- 2. AUTH ---
@portal_bp.route('/portal/auth', methods=['POST'])
def portal_auth():
    company_id = request.form.get('company_id')
    email = request.form.get('email')
    password = request.form.get('password')
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, name, password_hash FROM clients WHERE email=%s AND company_id=%s", (email, company_id))
        user = cur.fetchone()
        if user and user[2] and check_password_hash(user[2], password):
            session['portal_client_id'] = user[0]
            session['portal_company_id'] = company_id
            session['portal_client_name'] = user[1]
            return redirect(url_for('portal.portal_home'))
        else:
            flash("❌ Invalid credentials."); return redirect(url_for('portal.portal_login', company_id=company_id))
    finally: conn.close()

# --- 3. DASHBOARD ---
@portal_bp.route('/portal/home')
def portal_home():
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    cur.execute("SELECT name FROM clients WHERE id=%s", (client_id,))
    client_name = cur.fetchone()[0]

    # Active Jobs
    cur.execute("""
        SELECT j.id, j.ref, j.description, j.start_date, j.status, p.address_line1
        FROM jobs j LEFT JOIN properties p ON j.property_id = p.id
        WHERE j.client_id=%s AND j.status IN ('Scheduled', 'In Progress', 'Pending')
        ORDER BY j.start_date ASC
    """, (client_id,))
    raw_jobs = cur.fetchall()
    active_jobs = []
    for j in raw_jobs:
        job = list(j)
        job[3] = format_date_by_country(job[3], comp_id)
        active_jobs.append(job)

    # UPDATED: Fetch ONLY 'Active' Properties
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, p.type,
            (SELECT COUNT(*) FROM service_requests sr WHERE sr.property_id = p.id AND sr.status != 'Pending' AND sr.status != 'Completed'),
            p.gas_expiry, p.eicr_expiry, p.pat_expiry, p.epc_expiry
        FROM properties p 
        WHERE p.client_id=%s AND p.status = 'Active'
    """, (client_id,))
    
    raw_props = cur.fetchall()
    properties = []
    for p in raw_props:
        prop = list(p)
        # Check compliance for the badge
        checks = [get_compliance_status(prop[5]), get_compliance_status(prop[6]), get_compliance_status(prop[7]), get_compliance_status(prop[8])]
        
        # Calculate Badge Status
        overall_status = 'Good'
        # Filter out None values first
        valid_checks = [c for c in checks if c is not None]
        
        if any(c['status'] == 'Expired' for c in valid_checks): overall_status = 'Expired'
        elif any(c['status'] == 'Expiring' for c in valid_checks): overall_status = 'Warning'
        
        prop.append(overall_status)
        properties.append(prop)

    cur.execute("SELECT COUNT(*) FROM quotes WHERE client_id=%s AND status IN ('Draft','Sent')", (client_id,))
    open_quotes = cur.fetchone()[0]

    cur.execute("""
        SELECT sr.id, p.address_line1, sr.issue_description, sr.status, sr.created_at
        FROM service_requests sr JOIN properties p ON sr.property_id=p.id
        WHERE sr.client_id=%s ORDER BY sr.created_at DESC LIMIT 5
    """, (client_id,))
    recent_requests = []
    for r in cur.fetchall():
        req = list(r)
        req[4] = format_date_by_country(req[4], comp_id)
        recent_requests.append(req)

    conn.close()
    return render_template('portal/portal_home.html', company_name=config.get('name'), 
                         client_name=client_name, properties=properties, active_jobs=active_jobs,
                         open_quotes_count=open_quotes, recent_requests=recent_requests,
                         brand_color=config.get('color'), logo_url=config.get('logo'))

# --- 4. VIEW JOB ---
@portal_bp.route('/portal/job/<int:job_id>')
def portal_job_view(job_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.description, j.start_date, j.end_date, p.address_line1, p.postcode
        FROM jobs j LEFT JOIN properties p ON j.property_id = p.id WHERE j.id=%s AND j.client_id=%s
    """, (job_id, client_id))
    job_row = cur.fetchone()
    if not job_row: conn.close(); return "Not Found", 404
    job = list(job_row)
    job[4] = format_date_by_country(job[4], comp_id)
    job[5] = format_date_by_country(job[5], comp_id)

    cur.execute("SELECT filepath, uploaded_at FROM job_evidence WHERE job_id=%s ORDER BY uploaded_at DESC", (job_id,))
    raw_photos = cur.fetchall()
    photos = []
    for p in raw_photos:
        ph = list(p)
        ph[1] = format_date_by_country(ph[1], comp_id)
        photos.append(ph)
    conn.close()
    return render_template('portal/portal_job_view.html', job=job, photos=photos, company_name=config.get('name'), logo_url=config.get('logo'), brand_color=config.get('color'))

# --- 5. PROPERTY DETAIL (SMART COMPLIANCE) ---
@portal_bp.route('/portal/property/<int:property_id>')
def property_detail(property_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    cur.execute("""
        SELECT id, address_line1, postcode, type, tenant_name, tenant_phone, key_code,
               gas_expiry, eicr_expiry, pat_expiry, epc_expiry
        FROM properties WHERE id=%s AND client_id=%s
    """, (property_id, client_id))
    prop_row = cur.fetchone()
    if not prop_row: conn.close(); return redirect('/portal/home')

    # Build Smart Compliance Dictionary (Only include checks that have dates)
    compliance_raw = {
        'Gas Safety': prop_row[7],
        'EICR': prop_row[8],
        'PAT Test': prop_row[9],
        'EPC': prop_row[10]
    }
    
    compliance = {}
    for key, date_val in compliance_raw.items():
        if date_val: # Only process if date exists
            status_data = get_compliance_status(date_val)
            status_data['date'] = format_date_by_country(date_val, comp_id)
            compliance[key] = status_data

    cur.execute("SELECT id, ref, status, description, start_date FROM jobs WHERE property_id=%s ORDER BY start_date DESC", (property_id,))
    raw_history = cur.fetchall()
    job_history = []
    for h in raw_history:
        j = list(h)
        j[4] = format_date_by_country(j[4], comp_id)
        job_history.append(j)

    conn.close()
    return render_template('portal/portal_property_view.html', 
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'), logo_url=config.get('logo'), 
                         brand_color=config.get('color'), prop=prop_row, 
                         compliance=compliance, job_history=job_history)

# --- 6. ARCHIVE PROPERTY (WAS DELETE) ---
@portal_bp.route('/portal/property/archive/<int:property_id>', methods=['POST'])
def archive_property(property_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Soft Delete: Just change status to 'Archived'
        cur.execute("UPDATE properties SET status = 'Archived' WHERE id = %s AND client_id = %s", (property_id, client_id))
        conn.commit()
        flash("📦 Property archived successfully.", "success")
            
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect('/portal/home')

@portal_bp.route('/portal/quotes')
def portal_quotes():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch quotes for this client
    cur.execute("""
        SELECT id, reference, date, total, status 
        FROM quotes 
        WHERE client_id = %s AND status != 'Archived'
        ORDER BY date DESC
    """, (client_id,))
    
    quotes_raw = cur.fetchall()
    quotes = []
    
    for r in quotes_raw:
        q = list(r)
        q[2] = format_date_by_country(q[2], comp_id) # Format the date
        quotes.append(q)
        
    conn.close()
    
    return render_template('portal/portal_quotes.html',
                           client_name=session.get('portal_client_name'),
                           company_name=config.get('name'), 
                           logo_url=config.get('logo'),
                           brand_color=config.get('color'),
                           quotes=quotes)

@portal_bp.route('/portal/quote/<int:quote_id>')
def portal_view_quote(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    conn = get_db(); cur = conn.cursor()

    # 1. FETCH COMPANY SETTINGS (The "Brain" of the Quote)
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    config = {
        'name': settings.get('company_name', 'Our Company'),
        'email': settings.get('company_email', ''),
        'phone': settings.get('company_phone', ''),
        'address': settings.get('company_address', ''),
        'logo': settings.get('logo', ''),
        'color': settings.get('brand_color', '#333333'),
        'currency': settings.get('currency_symbol', '£')
    }

    # 2. FETCH QUOTE HEADER + JOB DETAILS
    cur.execute("""
        SELECT q.id, q.reference, q.date, q.total, q.status, 
               q.job_title, p.address_line1, p.postcode, q.job_description
        FROM quotes q
        LEFT JOIN properties p ON q.property_id = p.id
        WHERE q.id = %s AND q.client_id = %s
    """, (quote_id, client_id))
    quote_row = cur.fetchone()
    
    if not quote_row:
        conn.close()
        return "Quote not found or access denied", 404

    # 3. FETCH LINE ITEMS
    cur.execute("""
        SELECT description, quantity, unit_price, total 
        FROM quote_items 
        WHERE quote_id = %s ORDER BY id ASC
    """, (quote_id,))
    items_raw = cur.fetchall()
    items = []
    
    # Calculate Subtotal from Items (True Net)
    subtotal = 0.0
    for r in items_raw:
        subtotal += float(r[3] or 0)
        items.append(r)

    conn.close()

    # 4. TAX LOGIC (Matches Office/PDF Logic)
    vat_reg = settings.get('vat_registered', 'no')
    tax_rate = 0.0
    
    if vat_reg in ['yes', 'on', 'true', '1']:
        manual_rate = settings.get('default_tax_rate')
        if manual_rate: 
            tax_rate = float(manual_rate) / 100
        else:
            # Default Country Rates
            country = settings.get('country_code', 'UK')
            TAX_RATES = {'UK': 0.20, 'IE': 0.23, 'US': 0.00, 'CAN': 0.05, 'AUS': 0.10, 'NZ': 0.15}
            tax_rate = TAX_RATES.get(country, 0.20)

    tax_amount = subtotal * tax_rate
    grand_total = subtotal + tax_amount

    # Package Data
    quote = {
        'id': quote_row[0],
        'ref': quote_row[1],
        'date': format_date_by_country(quote_row[2], comp_id),
        'status': quote_row[4],
        'title': quote_row[5] or "General Quote",
        'site_address': f"{quote_row[6]}, {quote_row[7]}" if quote_row[6] else "No Site Address",
        'desc': quote_row[8],
        # Financials
        'subtotal': subtotal,
        'tax_rate_percent': int(tax_rate * 100),
        'tax_amount': tax_amount,
        'grand_total': grand_total
    }
    
    return render_template('portal/portal_quote_view.html',
                           client_name=session.get('portal_client_name'),
                           company_name=config['name'],
                           logo_url=config['logo'],
                           brand_color=config['color'],
                           config=config,
                           quote=quote,
                           items=items)

@portal_bp.route('/portal/quote/<int:quote_id>/accept')
def portal_accept_quote(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    conn = get_db(); cur = conn.cursor()
    
    try:
        # 1. MARK QUOTE AS ACCEPTED
        cur.execute("""
            UPDATE quotes 
            SET status = 'Accepted' 
            WHERE id = %s AND client_id = %s
            RETURNING reference, job_title, job_description, property_id, estimated_days, total, preferred_vehicle_id
        """, (quote_id, client_id))
        
        quote_row = cur.fetchone()
        
        if quote_row:
            # Unpack quote details
            q_ref, title, desc, prop_id, days, total, van_id = quote_row
            
            # 2. GENERATE JOB REFERENCE (e.g., Q-1001 -> JOB-1001)
            job_ref = q_ref.replace('Q-', 'JOB-')
            
            # Check if job already exists to prevent duplicates (Double Click Safety)
            cur.execute("SELECT id FROM jobs WHERE quote_id = %s", (quote_id,))
            existing_job = cur.fetchone()
            
            if not existing_job:
                # 3. INSERT INTO JOBS TABLE (Status 'Pending' puts it in the Calendar Sidebar)
                cur.execute("""
                    INSERT INTO jobs (
                        company_id, client_id, property_id, quote_id, 
                        ref, description, status, quote_total, 
                        estimated_days, vehicle_id, created_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'Pending', %s, %s, %s, NOW())
                    RETURNING id
                """, (comp_id, client_id, prop_id, quote_id, job_ref, title or desc, total, days, van_id))
                
                new_job_id = cur.fetchone()[0]

                # 4. COPY MATERIALS (So your Material List is ready)
                cur.execute("""
                    INSERT INTO job_materials (job_id, description, quantity, unit_price)
                    SELECT %s, description, quantity, unit_price 
                    FROM quote_items WHERE quote_id = %s
                """, (new_job_id, quote_id))
                
                flash("✅ Quote accepted! A new job has been created.", "success")
            else:
                flash("✅ Quote already accepted.", "info")
        
        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('portal.portal_view_quote', quote_id=quote_id))