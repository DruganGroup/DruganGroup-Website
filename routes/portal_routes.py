from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from werkzeug.security import check_password_hash, generate_password_hash
from services.enforcement import check_limit
from werkzeug.utils import secure_filename
from datetime import datetime, timedelta, date
from utils.certificates import get_country_compliance_labels, normalize_country_code

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
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS photo VARCHAR(255);")
        conn.commit()
    except:
        conn.rollback()

    try:
        cur.execute("SELECT id, name, password_hash, portal_access, photo FROM clients WHERE email=%s AND company_id=%s", (email, company_id))
        user = cur.fetchone()
        if user and user[2] and check_password_hash(user[2], password):
            if not user[3]:
                flash("❌ Your portal access has been disabled by the administration.")
                return redirect(url_for('portal.portal_login', company_id=company_id))
                
            session['portal_client_id'] = int(user[0])
            session['portal_company_id'] = int(company_id)
            session['portal_client_name'] = user[1]
            session['portal_client_photo'] = user[4] if user[4] else None
            return redirect(url_for('portal.portal_home'))
        else:
            flash("❌ Invalid credentials."); return redirect(url_for('portal.portal_login', company_id=company_id))
    finally: pass

# --- 3. DASHBOARD ---
@portal_bp.route('/portal/home')
def portal_home():
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    cur.execute("SELECT name, email, phone, photo FROM clients WHERE id=%s", (client_id,))
    client_row = cur.fetchone()
    client_name = client_row[0] if client_row else 'Client'
    if client_row and client_row[3]:
        session['portal_client_photo'] = client_row[3]

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

    # UPDATED: Fetch ONLY 'Active' Properties with rich compliance & counts + photo
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, p.type,
            (SELECT COUNT(*) FROM service_requests sr WHERE sr.property_id = p.id AND sr.status NOT IN ('Completed', 'Resolved', 'Cancelled', 'Finished')),
            p.gas_expiry, p.eicr_expiry, p.pat_expiry, p.epc_expiry,
            p.tenant_name, p.tenant_phone, p.photo
        FROM properties p 
        WHERE p.client_id=%s AND p.status = 'Active'
        ORDER BY p.id DESC
    """, (client_id,))
    
    raw_props = cur.fetchall()
    properties = []
    compliant_props_count = 0
    expiring_props_count = 0
    expired_props_count = 0

    for p in raw_props:
        prop = list(p)
        # Check compliance for each individual cert
        gas_check = get_compliance_status(prop[5])
        eicr_check = get_compliance_status(prop[6])
        pat_check = get_compliance_status(prop[7])
        epc_check = get_compliance_status(prop[8])

        checks = [gas_check, eicr_check, pat_check, epc_check]
        valid_checks = [c for c in checks if c is not None]
        
        # Calculate Badge Status
        overall_status = 'Good'
        if any(c['status'] == 'Expired' for c in valid_checks):
            overall_status = 'Expired'
            expired_props_count += 1
        elif any(c['status'] == 'Expiring' for c in valid_checks):
            overall_status = 'Warning'
            expiring_props_count += 1
        else:
            compliant_props_count += 1
        
        prop.append(overall_status)
        # Append structured checks for the UI
        prop.append({
            'gas': gas_check,
            'eicr': eicr_check,
            'pat': pat_check,
            'epc': epc_check
        })
        properties.append(prop)

    # Quotes Count
    cur.execute("SELECT COUNT(*) FROM quotes WHERE client_id=%s AND status IN ('Draft','Sent')", (client_id,))
    open_quotes = cur.fetchone()[0] or 0

    # Invoices KPI (Unpaid count & balance)
    cur.execute("""
        SELECT COUNT(*), COALESCE(SUM(total), 0) 
        FROM invoices 
        WHERE client_id=%s AND status NOT IN ('Paid', 'Cancelled', 'Draft')
    """, (client_id,))
    inv_stat = cur.fetchone()
    unpaid_invoices_count = inv_stat[0] or 0
    unpaid_invoices_total = float(inv_stat[1] or 0)

    # Open Requests Count
    cur.execute("""
        SELECT COUNT(*) FROM service_requests 
        WHERE client_id=%s AND status NOT IN ('Completed', 'Resolved', 'Cancelled', 'Finished')
    """, (client_id,))
    open_requests_count = cur.fetchone()[0] or 0

    # Recent Requests
    cur.execute("""
        SELECT sr.id, p.address_line1, sr.issue_description, sr.status, sr.created_at, sr.priority
        FROM service_requests sr JOIN properties p ON sr.property_id=p.id
        WHERE sr.client_id=%s ORDER BY sr.created_at DESC LIMIT 5
    """, (client_id,))
    recent_requests = []
    for r in cur.fetchall():
        req = list(r)
        req[4] = format_date_by_country(req[4], comp_id)
        recent_requests.append(req)

    kpi = {
        'total_properties': len(properties),
        'active_jobs': len(active_jobs),
        'open_quotes': open_quotes,
        'unpaid_invoices_count': unpaid_invoices_count,
        'unpaid_invoices_total': unpaid_invoices_total,
        'open_requests_count': open_requests_count,
        'compliant_props': compliant_props_count,
        'expiring_props': expiring_props_count,
        'expired_props': expired_props_count
    }

    return render_template('portal/portal_home.html', 
                           company_name=config.get('name'), 
                           client_name=client_name, 
                           properties=properties, 
                           active_jobs=active_jobs,
                           open_quotes_count=open_quotes, 
                           recent_requests=recent_requests,
                           kpi=kpi,
                           currency=config.get('currency', '£'),
                           brand_color=config.get('color', '#333333'), 
                           logo_url=config.get('logo'),
                           client_photo=session.get('portal_client_photo'))

# --- 4. VIEW JOB ---
@portal_bp.route('/portal/job/<int:job_id>')
def portal_job_view(job_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Job Details
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.description, j.start_date, j.end_date, p.address_line1, p.postcode, j.quote_id
        FROM jobs j LEFT JOIN properties p ON j.property_id = p.id WHERE j.id=%s AND j.client_id=%s
    """, (job_id, client_id))
    job_row = cur.fetchone()
    
    if not job_row: pass; return "Not Found", 404
    
    job = list(job_row)
    job[4] = format_date_by_country(job[4], comp_id)
    job[5] = format_date_by_country(job[5], comp_id)

    # 2. Fetch Connected Quote (if any)
    connected_quote = None
    if job[8]:
        cur.execute("SELECT id, reference, status, total, date, job_title FROM quotes WHERE id = %s AND client_id = %s", (job[8], client_id))
        q_row = cur.fetchone()
        if q_row:
            connected_quote = {
                'id': q_row[0], 'ref': q_row[1], 'status': q_row[2],
                'total': float(q_row[3] or 0), 'date': format_date_by_country(q_row[4], comp_id),
                'title': q_row[5] or f"Quote {q_row[1]}"
            }

    # 3. Fetch Connected Invoice (if any)
    cur.execute("""
        SELECT id, reference, status, total, date, due_date
        FROM invoices WHERE job_id = %s AND client_id = %s AND status != 'Void'
        ORDER BY id DESC LIMIT 1
    """, (job_id, client_id))
    inv_row = cur.fetchone()
    connected_invoice = None
    if inv_row:
        connected_invoice = {
            'id': inv_row[0], 'ref': inv_row[1], 'status': inv_row[2],
            'total': float(inv_row[3] or 0), 'date': format_date_by_country(inv_row[4], comp_id),
            'due_date': format_date_by_country(inv_row[5], comp_id)
        }

    # 4. Fetch ALL Site Photos + Evidence Files
    cur.execute("""
        SELECT filepath, uploaded_at, file_type 
        FROM job_evidence 
        WHERE job_id = %s 
        AND (visible_to_client = TRUE OR file_type IN ('Site Photo', 'Completion Photo', 'Progress Photo'))
        ORDER BY uploaded_at DESC
    """, (job_id,))
    
    raw_files = cur.fetchall()
    photos = []
    job_docs = []
    for p in raw_files:
        filepath = p[0]
        date_str = format_date_by_country(p[1], comp_id)
        file_type = p[2]
        is_pdf = filepath.lower().endswith('.pdf') if filepath else False
        
        item = {'path': filepath, 'date': date_str, 'type': file_type}
        
        if is_pdf or file_type in ['Project Plan', 'Layout Drawing', 'Building Rights', 'Certificate']:
            job_docs.append(item)
        else:
            photos.append(item)

    # 5. Fetch Site Diary & Communication Timeline
    cur.execute("""
        SELECT id, staff_name, entry_text, created_at
        FROM site_diary 
        WHERE job_id = %s
        ORDER BY created_at ASC
    """, (job_id,))
    diary_rows = cur.fetchall()
    timeline_logs = []
    for d in diary_rows:
        timeline_logs.append({
            'id': d[0],
            'author': d[1] or 'Site Team',
            'message': d[2],
            'date': format_date_by_country(d[3], comp_id) if d[3] else '',
            'time': d[3].strftime('%H:%M') if (d[3] and hasattr(d[3], 'strftime')) else ''
        })
    
    return render_template('portal/portal_job_view.html', 
                           job=job, 
                           photos=photos, 
                           job_docs=job_docs,
                           connected_quote=connected_quote,
                           connected_invoice=connected_invoice,
                           timeline_logs=timeline_logs,
                           company_name=config.get('name'), 
                           company_email=config.get('email'),
                           logo_url=config.get('logo'), 
                           brand_color=config.get('color'))

@portal_bp.route('/portal/job/<int:job_id>/add-message', methods=['POST'])
def portal_job_add_message(job_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    client_name = session.get('portal_client_name', 'Client')
    comp_id = session['portal_company_id']
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM jobs WHERE id=%s AND client_id=%s AND company_id=%s", (job_id, client_id, comp_id))
    if not cur.fetchone():
        return "Unauthorized", 403
        
    msg = request.form.get('message', '').strip()
    if msg:
        cur.execute(
            "INSERT INTO site_diary (job_id, staff_name, entry_text) VALUES (%s, %s, %s)",
            (job_id, f"Client ({client_name})", msg)
        )
        conn.commit()
        flash("Your message was posted to the site team & office timeline.", "success")
        
    return redirect(f"/portal/job/{job_id}")

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
               gas_expiry, eicr_expiry, pat_expiry, epc_expiry, photo
        FROM properties WHERE id=%s AND client_id=%s
    """, (property_id, client_id))
    prop_row = cur.fetchone()
    if not prop_row: pass; return redirect('/portal/home')

    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (comp_id,))
    cc_row = cur.fetchone()
    country_code = cc_row[0] if cc_row and cc_row[0] else 'UK'
    labels = get_country_compliance_labels(country_code)

    # Build Smart Compliance Dictionary with Country Specific Legal Test Names
    compliance_raw = {
        labels['gas']['full']: prop_row[7],
        labels['eicr']['full']: prop_row[8],
        labels['pat']['full']: prop_row[9],
        labels['epc']['full']: prop_row[10]
    }
    
    cert_map = {
        labels['gas']['full']: ['CP12', 'Gas Safe', 'Landlord Cert', 'gas_cert', 'qualigaz', 'gas_dvgw', 'rgii_gas', 'gas_nz', 'epa_energy', 'Civil Defense Gas Safety'],
        labels['eicr']['full']: ['EICR', 'Electrical', 'Electrical Installation', 'cie_elec', 'consuel', 'dguv_v3', 'safe_elec', 'esc_elec', 'ccew', 'esa_defect', 'nfpa70e', 'dewa_elec'],
        labels['epc']['full']: ['EPC', 'Energy Performance', 'DPE', 'GEG', 'BER', 'NZGBC', 'NatH', 'ENG', 'EPA Energy Audit'],
        labels['pat']['full']: ['PAT Test', 'Portable Appliance Testing', 'ITP', 'SEC', 'VDE', 'OSHA', 'CSA', 'TAG', 'Civil Defense Life Safety']
    }

    compliance = {}
    for key, date_val in compliance_raw.items():
        if date_val:
            status_data = get_compliance_status(date_val)
            status_data['date'] = format_date_by_country(date_val, comp_id)
            
            # Find latest PDF file for this cert type
            cur.execute("""
                SELECT je.filepath 
                FROM job_evidence je
                JOIN jobs j ON je.job_id = j.id
                WHERE j.property_id = %s 
                AND je.file_type = ANY(%s)
                ORDER BY je.uploaded_at DESC LIMIT 1
            """, (property_id, cert_map.get(key, [])))
            
            file_row = cur.fetchone()
            if file_row:
                status_data['download_url'] = file_row[0]

            compliance[key] = status_data

    cur.execute("SELECT id, ref, status, description, start_date FROM jobs WHERE property_id=%s ORDER BY start_date DESC", (property_id,))
    raw_history = cur.fetchall()
    job_history = []
    for h in raw_history:
        j = list(h)
        j[4] = format_date_by_country(j[4], comp_id)
        job_history.append(j)

    cur.execute("""
        SELECT document_type, filepath, uploaded_at 
        FROM property_documents 
        WHERE property_id = %s AND company_id = %s AND visible_to_client = TRUE
        ORDER BY uploaded_at DESC
    """, (property_id, comp_id))
    prop_docs = [{'type': r[0], 'path': r[1], 'date': format_date_by_country(r[2], comp_id)} for r in cur.fetchall()]

    pass
    return render_template('portal/portal_property_view.html', 
                         client_name=session.get('portal_client_name'),
                         company_name=config.get('name'), logo_url=config.get('logo'), 
                         brand_color=config.get('color'), prop=prop_row, 
                         compliance=compliance, job_history=job_history, prop_docs=prop_docs)

# --- 6. ARCHIVE PROPERTY (WAS DELETE) ---
@portal_bp.route('/portal/request/submit', methods=['POST'])
def portal_request_submit():
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    prop_id = request.form.get('property_id')
    desc = request.form.get('description')
    severity = request.form.get('severity') or request.form.get('priority') or 'Medium'
    if severity not in ['Low', 'Medium', 'High', 'Emergency']:
        severity = 'Medium'
    
    conn = get_db(); cur = conn.cursor()
    
    # DB Update for photo_path
    try:
        cur.execute("ALTER TABLE service_requests ADD COLUMN IF NOT EXISTS photo_path TEXT;")
        conn.commit()
    except:
        conn.rollback()

    photo_path = None
    if 'photo' in request.files:
        f = request.files['photo']
        if f and f.filename != '':
            from werkzeug.utils import secure_filename
            import os
            from flask import current_app
            save_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'requests')
            os.makedirs(save_dir, exist_ok=True)
            from datetime import datetime
            fn = secure_filename(f"req_{int(datetime.now().timestamp())}_{f.filename}")
            f.save(os.path.join(save_dir, fn))
            photo_path = f"/uploads/company_{comp_id}/requests/{fn}"

    try:
        cur.execute("""
            INSERT INTO service_requests (company_id, client_id, property_id, issue_description, priority, status, photo_path)
            VALUES (%s, %s, %s, %s, %s, 'Pending', %s)
        """, (comp_id, client_id, prop_id, desc, severity, photo_path))
        conn.commit()
        from flask import flash
        flash("✅ Issue reported successfully. The office has been notified.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error submitting request: {e}", "error")
    finally:
        pass

    return redirect(f'/portal/property/{prop_id}')

# --- 7. ADD PROPERTY ---
@portal_bp.route('/portal/property/add', methods=['POST'])
def portal_add_property():
    if not check_portal_access(): return redirect(get_login_url())
    
    comp_id = session.get('portal_company_id')
    client_id = session.get('portal_client_id')
    
    allowed, msg = check_limit(comp_id, 'max_properties')
    if not allowed:
        flash(msg, "error")
        return redirect(url_for('portal.portal_properties'))
        
    addr = request.form.get('address')
    postcode = request.form.get('postcode')
    prop_type = request.form.get('type')
    tenant_name = request.form.get('tenant_name')
    tenant_phone = request.form.get('tenant_phone')
    tenant_email = request.form.get('tenant_email')
    key_code = request.form.get('key_code')
    
    photo_file = request.files.get('property_photo') or request.files.get('photo')
    from routes.client_routes import save_property_photo
    photo_path = save_property_photo(photo_file, comp_id)
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, type, tenant_name, tenant_phone, tenant_email, key_code, photo, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'Active')
        """, (comp_id, client_id, addr, postcode, prop_type, tenant_name, tenant_phone, tenant_email, key_code, photo_path))
        conn.commit()
        flash("✅ Property added successfully.", "success")
    except Exception as e:
        conn.rollback(); flash(f"Error adding property: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('portal.portal_home'))

@portal_bp.route('/portal/property/<int:property_id>/upload-photo', methods=['POST'])
def portal_upload_property_photo(property_id):
    if not check_portal_access(): return redirect(get_login_url())
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    photo_file = request.files.get('property_photo') or request.files.get('photo')
    if not photo_file or not photo_file.filename:
        flash("❌ Please select a photo file to upload.", "warning")
        return redirect(f'/portal/property/{property_id}')
        
    from routes.client_routes import save_property_photo
    new_photo = save_property_photo(photo_file, comp_id)
    if new_photo:
        conn = get_db(); cur = conn.cursor()
        cur.execute("UPDATE properties SET photo = %s WHERE id = %s AND client_id = %s", (new_photo, property_id, client_id))
        conn.commit()
        flash("📸 Property photo updated successfully!", "success")
    else:
        flash("❌ Could not save photo. Please try another image format.", "error")
        
    return redirect(f'/portal/property/{property_id}')

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
        pass
        
    return redirect('/portal/home')

@portal_bp.route('/portal/invoices')
def portal_invoices():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT i.id, i.reference, i.date, i.due_date, i.total, i.status,
               COALESCE(q.job_title, j.description, 'Invoice') as title,
               q.id as quote_id, q.reference as quote_ref,
               j.id as job_id, j.ref as job_ref
        FROM invoices i 
        LEFT JOIN jobs j ON i.job_id = j.id
        LEFT JOIN quotes q ON i.quote_id = q.id
        WHERE i.client_id = %s AND i.status != 'Archived'
        ORDER BY i.date DESC
    """, (client_id,))
    
    invoices_raw = cur.fetchall()
    invoices = []
    
    for r in invoices_raw:
        invoices.append({
            'id': r[0],
            'ref': r[1],
            'date': format_date_by_country(r[2], comp_id),
            'due_date': format_date_by_country(r[3], comp_id),
            'total': float(r[4] or 0),
            'status': r[5],
            'title': r[6],
            'quote_id': r[7],
            'quote_ref': r[8],
            'job_id': r[9],
            'job_ref': r[10]
        })
        
    return render_template('portal/portal_invoices.html',
                           client_name=session.get('portal_client_name'),
                           company_name=config.get('name'), 
                           logo_url=config.get('logo'),
                           brand_color=config.get('color'),
                           invoices=invoices)

@portal_bp.route('/portal/invoice/<int:invoice_id>')
def portal_view_invoice(invoice_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    conn = get_db(); cur = conn.cursor()

    # 1. Company Settings
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

    # 2. Fetch Invoice Header + Job / Quote details
    cur.execute("""
        SELECT i.id, i.reference, i.date, i.due_date, i.total, i.status,
               COALESCE(q.job_title, j.description, 'Invoice') as job_title,
               COALESCE(q.job_description, j.description, '') as job_desc,
               COALESCE(p.address_line1, ''), COALESCE(p.postcode, ''),
               i.subtotal, i.tax,
               i.job_id, j.ref as job_ref, j.status as job_status,
               i.quote_id, q.reference as quote_ref, q.status as quote_status
        FROM invoices i
        LEFT JOIN jobs j ON i.job_id = j.id
        LEFT JOIN quotes q ON i.quote_id = q.id
        LEFT JOIN properties p ON (j.property_id = p.id OR q.property_id = p.id)
        WHERE i.id = %s AND i.client_id = %s AND i.company_id = %s
    """, (invoice_id, client_id, comp_id))
    inv_row = cur.fetchone()
    
    if not inv_row:
        return "Invoice not found or access denied", 404

    # 3. Line Items
    cur.execute("""
        SELECT description, quantity, unit_price, total
        FROM invoice_items
        WHERE invoice_id = %s ORDER BY id ASC
    """, (invoice_id,))
    items_raw = cur.fetchall()
    items = []
    items_total_sum = 0.0
    
    for r in items_raw:
        line_tot = float(r[3] or 0)
        items_total_sum += line_tot
        items.append({
            'desc': r[0],
            'qty': r[1],
            'price': float(r[2] or 0),
            'total': line_tot
        })
        
    from services.tax_engine import TaxEngine
    comp_tax_rate = TaxEngine.get_tax_rate(settings)
    
    stored_subtotal = float(inv_row[10]) if inv_row[10] is not None else None
    stored_tax = float(inv_row[11]) if inv_row[11] is not None else None
    grand_total = float(inv_row[4] or 0.0)
    
    if stored_subtotal is not None and stored_tax is not None:
        subtotal = stored_subtotal
        tax_amount = stored_tax
    elif comp_tax_rate > 0:
        divisor = 1 + comp_tax_rate
        subtotal = grand_total / divisor
        tax_amount = grand_total - subtotal
    else:
        subtotal = grand_total if grand_total > 0 else items_total_sum
        tax_amount = 0.0

    if not items:
        items.append({
            'desc': inv_row[6] or 'Standard Invoiced Services',
            'qty': 1,
            'price': subtotal,
            'total': subtotal
        })

    tax_rate_percent = int(round((tax_amount / subtotal) * 100)) if (subtotal > 0 and tax_amount > 0) else 0

    site_addr = f"{inv_row[8]}, {inv_row[9]}" if inv_row[8] else ""

    connected_job = None
    if inv_row[12]:
        connected_job = {'id': inv_row[12], 'ref': inv_row[13], 'status': inv_row[14]}
        
    connected_quote = None
    if inv_row[15]:
        connected_quote = {'id': inv_row[15], 'ref': inv_row[16], 'status': inv_row[17]}

    invoice = {
        'id': inv_row[0],
        'ref': inv_row[1],
        'date': format_date_by_country(inv_row[2], comp_id),
        'due_date': format_date_by_country(inv_row[3], comp_id),
        'status': inv_row[5],
        'title': inv_row[6] or "Invoice",
        'desc': inv_row[7] or "",
        'site_address': site_addr,
        'subtotal': subtotal,
        'tax_rate_percent': tax_rate_percent,
        'tax_amount': tax_amount,
        'grand_total': grand_total
    }

    return render_template('portal/portal_invoice_view.html',
                           client_name=session.get('portal_client_name'),
                           company_name=config['name'],
                           logo_url=config['logo'],
                           brand_color=config['color'],
                           config=config,
                           invoice=invoice,
                           items=items,
                           connected_job=connected_job,
                           connected_quote=connected_quote)

@portal_bp.route('/portal/invoice/<int:invoice_id>/download')
def portal_download_invoice(invoice_id):
    if not check_portal_access(): return redirect(get_login_url())
    return redirect(f"/finance/invoice/{invoice_id}/download")

@portal_bp.route('/portal/quote/<int:quote_id>/download')
def portal_download_quote(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    return redirect(f"/office/quote/{quote_id}/download")

@portal_bp.route('/portal/quotes')
def portal_quotes():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch quotes for this client with connected job / invoice status
    cur.execute("""
        SELECT q.id, q.reference, q.date, q.total, q.status, q.job_title,
               j.id as job_id, j.status as job_status, j.ref as job_ref,
               i.id as invoice_id, i.status as invoice_status, i.reference as invoice_ref
        FROM quotes q 
        LEFT JOIN jobs j ON j.quote_id = q.id
        LEFT JOIN invoices i ON (i.quote_id = q.id OR (i.job_id IS NOT NULL AND i.job_id = j.id))
        WHERE q.client_id = %s AND q.status != 'Archived'
        ORDER BY q.date DESC
    """, (client_id,))
    
    quotes_raw = cur.fetchall()
    quotes = []
    
    for r in quotes_raw:
        quotes.append({
            'id': r[0],
            'ref': r[1],
            'date': format_date_by_country(r[2], comp_id),
            'total': float(r[3] or 0),
            'status': r[4],
            'title': r[5] or f"Quote {r[1]}",
            'job_id': r[6],
            'job_status': r[7],
            'job_ref': r[8],
            'invoice_id': r[9],
            'invoice_status': r[10],
            'invoice_ref': r[11]
        })
        
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
        pass
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

    pass

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

    cur.execute("""
        SELECT document_type, filepath, uploaded_at 
        FROM quote_documents 
        WHERE quote_id = %s AND company_id = %s AND visible_to_client = TRUE
        ORDER BY uploaded_at DESC
    """, (quote_id, comp_id))
    quote_docs = [{'type': r[0], 'path': r[1], 'date': format_date_by_country(r[2], comp_id)} for r in cur.fetchall()]

    # 5. FETCH CONNECTED JOB (if converted/accepted)
    cur.execute("""
        SELECT id, ref, status, start_date, end_date, description
        FROM jobs 
        WHERE quote_id = %s AND client_id = %s
        ORDER BY id DESC LIMIT 1
    """, (quote_id, client_id))
    job_match = cur.fetchone()
    connected_job = None
    if job_match:
        connected_job = {
            'id': job_match[0],
            'ref': job_match[1],
            'status': job_match[2],
            'start_date': format_date_by_country(job_match[3], comp_id),
            'end_date': format_date_by_country(job_match[4], comp_id),
            'desc': job_match[5]
        }

    # 6. FETCH CONNECTED INVOICE (if generated)
    cur.execute("""
        SELECT id, reference, status, total, date, due_date
        FROM invoices 
        WHERE (quote_id = %s OR (job_id IS NOT NULL AND job_id = %s)) AND client_id = %s AND status != 'Void'
        ORDER BY id DESC LIMIT 1
    """, (quote_id, connected_job['id'] if connected_job else -1, client_id))
    inv_match = cur.fetchone()
    connected_invoice = None
    if inv_match:
        connected_invoice = {
            'id': inv_match[0],
            'ref': inv_match[1],
            'status': inv_match[2],
            'total': float(inv_match[3] or 0),
            'date': format_date_by_country(inv_match[4], comp_id),
            'due_date': format_date_by_country(inv_match[5], comp_id)
        }

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
                           items=items,
                           quote_docs=quote_docs,
                           connected_job=connected_job,
                           connected_invoice=connected_invoice)

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
        pass
        
    return redirect(url_for('portal.portal_view_quote', quote_id=quote_id))

@portal_bp.route('/portal/quote/<int:quote_id>/decline', methods=['POST'])
def portal_decline_quote(quote_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    reason = request.form.get('decline_reason', 'No reason provided')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE quotes 
            SET status = 'Declined', 
                client_response = %s,
                needs_followup = TRUE
            WHERE id = %s AND client_id = %s
        """, (reason, quote_id, client_id))
        
        conn.commit()
        flash("Quote has been declined. Thank you for your feedback.", "info")
    except Exception as e:
        conn.rollback()
        flash(f"Error declining quote: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('portal.portal_view_quote', quote_id=quote_id))
    
@portal_bp.route('/portal/request/<int:request_id>')
def portal_view_request(request_id):
    if not check_portal_access(): return redirect(get_login_url())
    
    conn = get_db(); cur = conn.cursor()

    # 1. Fetch Request Details
    cur.execute("""
        SELECT sr.id, sr.issue_description, sr.status, sr.created_at, 
               sr.priority, p.address_line1, p.postcode, sr.property_id
        FROM service_requests sr
        JOIN properties p ON sr.property_id = p.id
        WHERE sr.id = %s AND sr.client_id = %s
    """, (request_id, session['portal_client_id']))
    req = cur.fetchone()
    
    if not req: 
        pass
        return "Request not found", 404

    # 2. Fetch Completion Report & Linked Job Status
    cur.execute("""
        SELECT j.work_summary, j.end_date, 
               (SELECT filepath FROM job_evidence WHERE job_id = j.id AND (file_type='Completion Photo' OR file_type='Site Photo') LIMIT 1),
               (SELECT name FROM staff WHERE id = j.engineer_id)
        FROM jobs j WHERE service_request_id = %s AND j.status = 'Completed'
        ORDER BY j.id DESC LIMIT 1
    """, (request_id,))
    completion = cur.fetchone()

    cur.execute("""
        SELECT j.id, j.ref, j.status, j.start_date, (SELECT name FROM staff WHERE id = j.engineer_id) as eng_name
        FROM jobs j WHERE service_request_id = %s
        ORDER BY j.id DESC LIMIT 1
    """, (request_id,))
    scheduled_job = cur.fetchone()

    # 3. Fetch Timeline Updates (The New Feature)
    # Note: Ensure you have run the SQL to create the 'request_updates' table first
    updates = []
    try:
        cur.execute("""
            SELECT message, author, created_at 
            FROM request_updates 
            WHERE request_id = %s AND is_public = TRUE 
            ORDER BY created_at DESC
        """, (request_id,))
        updates = cur.fetchall()
    except Exception:
        pass # Table might not exist yet, fail gracefully

    comp_id = session.get('portal_company_id', 1)
    config = get_site_config(comp_id)

    return render_template('portal/portal_request_view.html', 
                           req=req, 
                           completion=completion, 
                           scheduled_job=scheduled_job,
                           updates=updates,
                           company_name=config.get('name'),
                           company_email=config.get('email'),
                           logo_url=config.get('logo'),
                           brand_color=config.get('color', '#333333'),
                           client_name=session.get('portal_client_name', 'Client'),
                           client_photo=session.get('portal_client_photo'))

@portal_bp.route('/portal/settings', methods=['GET', 'POST'])
def portal_settings():
    if not check_portal_access(): return redirect(get_login_url())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    try:
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS photo VARCHAR(255);")
        conn.commit()
    except:
        conn.rollback()
    
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        password = request.form.get('password')

        # Handle Logo/Photo Upload
        photo_path = None
        if 'photo' in request.files:
            f = request.files['photo']
            if f and f.filename != '':
                from werkzeug.utils import secure_filename
                import os
                from flask import current_app
                save_dir = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'clients')
                os.makedirs(save_dir, exist_ok=True)
                from datetime import datetime
                fn = secure_filename(f"client_{client_id}_{int(datetime.now().timestamp())}_{f.filename}")
                f.save(os.path.join(save_dir, fn))
                photo_path = f"uploads/company_{comp_id}/clients/{fn}"
                session['portal_client_photo'] = photo_path
        
        try:
            if photo_path and password:
                hashed_pass = generate_password_hash(password)
                cur.execute("""
                    UPDATE clients SET name = %s, phone = %s, password_hash = %s, photo = %s 
                    WHERE id = %s AND company_id = %s
                """, (name, phone, hashed_pass, photo_path, client_id, comp_id))
            elif photo_path:
                cur.execute("""
                    UPDATE clients SET name = %s, phone = %s, photo = %s 
                    WHERE id = %s AND company_id = %s
                """, (name, phone, photo_path, client_id, comp_id))
            elif password:
                hashed_pass = generate_password_hash(password)
                cur.execute("""
                    UPDATE clients SET name = %s, phone = %s, password_hash = %s 
                    WHERE id = %s AND company_id = %s
                """, (name, phone, hashed_pass, client_id, comp_id))
            else:
                cur.execute("""
                    UPDATE clients SET name = %s, phone = %s 
                    WHERE id = %s AND company_id = %s
                """, (name, phone, client_id, comp_id))
                
            conn.commit()
            session['portal_client_name'] = name
            flash("✅ Account settings and logo updated successfully.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"Error updating settings: {e}", "error")
            
        return redirect(url_for('portal.portal_settings'))
        
    cur.execute("SELECT name, email, phone, photo FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
    client_row = cur.fetchone()
    
    client_data = {
        'name': client_row[0],
        'email': client_row[1],
        'phone': client_row[2] or '',
        'photo': client_row[3] if client_row and client_row[3] else None
    }
    if client_data['photo']:
        session['portal_client_photo'] = client_data['photo']
    
    return render_template('portal/portal_settings.html',
                           client=client_data,
                           client_name=session.get('portal_client_name'),
                           company_name=config.get('name'), 
                           logo_url=config.get('logo'),
                           brand_color=config.get('color', '#333333'),
                           client_photo=session.get('portal_client_photo'))
