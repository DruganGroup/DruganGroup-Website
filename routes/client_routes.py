from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify, current_app
from db import get_db, get_site_config
from datetime import date, datetime
import os
from werkzeug.utils import secure_filename

try:
    from services.enforcement import check_limit
except ImportError:
    # Fallback if service missing
    def check_limit(comp_id, limit_type): return True, ""

try:
    from telematics_engine import get_tracker_data
except ImportError:
    get_tracker_data = None

client_bp = Blueprint('client', __name__)

def save_client_photo(file, comp_id):
    if not file or not file.filename:
        return None
    filename = f"client_{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
    folder = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'clients')
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, filename)
    file.save(file_path)
    return f"uploads/company_{comp_id}/clients/{filename}"

def save_property_photo(file, comp_id):
    if not file or not file.filename:
        return None
    filename = f"prop_{int(datetime.now().timestamp())}_{secure_filename(file.filename)}"
    folder = os.path.join(current_app.static_folder, 'uploads', f"company_{comp_id}", 'properties')
    os.makedirs(folder, exist_ok=True)
    file_path = os.path.join(folder, filename)
    file.save(file_path)
    return f"uploads/company_{comp_id}/properties/{filename}"

# =========================================================
# 1. CLIENT DASHBOARD & CREATION
# =========================================================

@client_bp.route('/clients')
def client_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # Ensure photo columns exist
    cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS photo VARCHAR(255);")
    cur.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS photo VARCHAR(255);")
    conn.commit()

    cur.execute("""
        SELECT id, name, email, phone, site_address, status, gate_code, billing_address, notes, portal_access, photo 
        FROM clients WHERE company_id = %s ORDER BY name ASC
    """, (comp_id,))
    clients = cur.fetchall()
    
    return render_template('clients/client_dashboard.html', 
                           clients=clients, 
                           brand_color=config['color'], 
                           logo_url=config['logo'])

@client_bp.route('/clients/add', methods=['POST'])
def add_client():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    
    # Check limits
    allowed, msg = check_limit(comp_id, 'max_clients')
    if not allowed:
        flash(msg, "error")
        return redirect(url_for('client.client_dashboard'))

    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    
    billing_addr = request.form.get('billing_address')
    portal_access = 1 if request.form.get('portal_access') == 'on' else 0
    safe_addr = billing_addr if billing_addr and billing_addr.strip() else "Address Pending"
    
    # Handle Photo upload
    photo_file = request.files.get('client_photo') or request.files.get('photo')
    photo_path = save_client_photo(photo_file, comp_id)
    
    from utils.db_utils import db_transaction
    with db_transaction() as cur:
        from werkzeug.security import generate_password_hash
        import secrets
        import string
        from tasks import send_client_portal_invite_task
        
        hashed_pass = None
        temp_pass = None
        
        if portal_access == 1:
            alphabet = string.ascii_letters + string.digits
            temp_pass = ''.join(secrets.choice(alphabet) for i in range(10))
            hashed_pass = generate_password_hash(temp_pass)

        # 1. Create Client with photo
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, billing_address, status, password_hash, portal_access, photo)
            VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s, %s)
            RETURNING id
        """, (comp_id, name, email, phone, safe_addr, hashed_pass, portal_access, photo_path))
        new_id = cur.fetchone()[0]
        
        # 2. Create First Property
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, type, status)
            VALUES (%s, %s, %s, '', 'Property', 'Active')
        """, (comp_id, new_id, safe_addr))
        
        # 3. Fetch Company Details to construct the portal URL
        cur.execute("SELECT COALESCE(sub_domain, subdomain), name FROM companies WHERE id = %s", (comp_id,))
        comp_row = cur.fetchone()
        
        flash("✅ Client Added")
        
        if portal_access == 1 and email and comp_row and comp_row[0]:
            subdomain = comp_row[0]
            company_name = comp_row[1]
            portal_url = f"https://{subdomain}.businessbetter.co.uk/portal/login/{comp_id}"
            
            send_client_portal_invite_task.delay(
                company_id=comp_id,
                client_email=email,
                client_name=name,
                temp_pass=temp_pass,
                portal_url=portal_url,
                company_name=company_name
            )
            flash("✉️ Welcome email with portal details is being sent to the client.", "info")

    return redirect(url_for('client.client_dashboard'))

@client_bp.route('/clients/update', methods=['POST'])
def update_client():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
    client_id = request.form.get('client_id')
    comp_id = session.get('company_id')
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    status = request.form.get('status')
    billing_address = request.form.get('billing_address')
    notes = request.form.get('notes')
    portal_access = 1 if request.form.get('portal_access') == 'on' else 0

    photo_file = request.files.get('client_photo') or request.files.get('photo')
    new_photo_path = save_client_photo(photo_file, comp_id)

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("SELECT portal_access, password_hash, photo FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
        row = cur.fetchone()
        
        needs_password = False
        temp_pass = None
        hashed_pass = None
        current_photo = row[2] if row else None
        final_photo = new_photo_path if new_photo_path else current_photo

        if row:
            current_access = row[0]
            has_password = bool(row[1])
            if portal_access == 1 and (current_access == 0 or not has_password):
                needs_password = True
                
        if needs_password:
            from werkzeug.security import generate_password_hash
            import secrets
            import string
            
            alphabet = string.ascii_letters + string.digits
            temp_pass = ''.join(secrets.choice(alphabet) for i in range(10))
            hashed_pass = generate_password_hash(temp_pass)
            
            cur.execute("""
                UPDATE clients SET 
                    name=%s, email=%s, phone=%s, status=%s, billing_address=%s, notes=%s, portal_access=%s, password_hash=%s, photo=%s
                WHERE id=%s AND company_id=%s
            """, (name, email, phone, status, billing_address, notes, portal_access, hashed_pass, final_photo, client_id, comp_id))
            
            cur.execute("SELECT COALESCE(sub_domain, subdomain), name FROM companies WHERE id = %s", (comp_id,))
            comp_row = cur.fetchone()
            
            if email and comp_row and comp_row[0]:
                from tasks import send_client_portal_invite_task
                subdomain = comp_row[0]
                company_name = comp_row[1]
                portal_url = f"https://{subdomain}.businessbetter.co.uk/portal/login/{comp_id}"
                
                send_client_portal_invite_task.delay(
                    company_id=comp_id,
                    client_email=email,
                    client_name=name,
                    temp_pass=temp_pass,
                    portal_url=portal_url,
                    company_name=company_name
                )
                flash("✉️ Portal access enabled. Welcome email sent to client.", "info")
        else:
            cur.execute("""
                UPDATE clients SET 
                    name=%s, email=%s, phone=%s, status=%s, billing_address=%s, notes=%s, portal_access=%s, photo=%s
                WHERE id=%s AND company_id=%s
            """, (name, email, phone, status, billing_address, notes, portal_access, final_photo, client_id, comp_id))
            flash("✅ Client updated successfully.")

        conn.commit()
    except Exception as e:
        conn.rollback(); flash(f"Error updating client: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('client.client_dashboard'))

# =========================================================
# 2. SINGLE CLIENT VIEW
# =========================================================

@client_bp.route('/client/<int:client_id>')
def view_client(client_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    if not comp_id:
        return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # Ensure columns exist
    cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS photo VARCHAR(255);")
    cur.execute("ALTER TABLE properties ADD COLUMN IF NOT EXISTS photo VARCHAR(255);")
    conn.commit()
    
    # Verify client belongs to user's company
    cur.execute("SELECT company_id FROM clients WHERE id = %s", (client_id,))
    client_row = cur.fetchone()
    if not client_row or client_row[0] != comp_id:
        return "Unauthorized: Client not found or belongs to different company", 403
    
    # 1. Fetch Client Details (With Billing, Notes & Photo)
    cur.execute("""
        SELECT id, name, email, phone, billing_address, notes, photo 
        FROM clients 
        WHERE id = %s AND company_id = %s
    """, (client_id, comp_id))
    client_row = cur.fetchone()
    
    if not client_row:
        return "Client not found", 404

    client = {
        'id': client_row[0], 'name': client_row[1], 'email': client_row[2], 
        'phone': client_row[3], 'billing_address': client_row[4], 'notes': client_row[5],
        'photo': client_row[6]
    }

    # 2. Fetch Properties (Including Photo)
    cur.execute("""
        SELECT id, address_line1, postcode, city, tenant_name, tenant_phone, 
               key_code, gas_expiry, eicr_expiry, pat_expiry, epc_expiry, photo
        FROM properties 
        WHERE client_id = %s 
        ORDER BY address_line1
    """, (client_id,))
    
    properties = []
    cols = ['id', 'address_line1', 'postcode', 'city', 'tenant_name', 'tenant_phone', 
            'key_code', 'gas_expiry', 'eicr_expiry', 'pat_expiry', 'epc_expiry', 'photo']
            
    for row in cur.fetchall():
        properties.append(dict(zip(cols, row)))

    # 3. Fetch Invoices
    cur.execute("""
        SELECT id, reference, total, status, date 
        FROM invoices 
        WHERE client_id = %s 
        ORDER BY date DESC
    """, (client_id,))
    invoices = cur.fetchall()

    # 4. Fetch Country and Certificates
    cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (comp_id,))
    country_row = cur.fetchone()
    country_code = country_row[0] if country_row else 'UK'
    
    from utils.certificates import get_certificates_for_country
    certificates = get_certificates_for_country(country_code)
    
    return render_template('office/client_details.html', 
                           client=client, 
                           properties=properties, 
                           invoices=invoices,
                           certificates=certificates,
                           current_date=date.today())

# =========================================================
# 3. PROPERTY MANAGEMENT (Add/View/Update)
# =========================================================

@client_bp.route('/office/client/<int:client_id>/add-property', methods=['POST'])
def add_property(client_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    addr = request.form.get('address')
    post = request.form.get('postcode')
    tenant = request.form.get('tenant_name')
    t_phone = request.form.get('tenant_phone') 
    t_email = request.form.get('tenant_email')
    key = request.form.get('key_code')
    
    gas = request.form.get('gas_expiry') or None
    eicr = request.form.get('eicr_expiry') or None
    pat = request.form.get('pat_expiry') or None
    epc = request.form.get('epc_expiry') or None
    
    photo_file = request.files.get('property_photo') or request.files.get('photo')
    photo_path = save_property_photo(photo_file, comp_id)
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, tenant_name, tenant_phone, tenant_email, key_code, gas_expiry, eicr_expiry, pat_expiry, epc_expiry, photo)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, addr, post, tenant, t_phone, t_email, key, gas, eicr, pat, epc, photo_path))
        conn.commit()
        flash("✅ Property added successfully.")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('client.view_client', client_id=client_id))

@client_bp.route('/office/property/<int:property_id>')
def view_property(property_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Property & Client
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, p.city, 
               p.tenant_name, p.tenant_phone, p.key_code,
               p.gas_expiry, p.eicr_expiry, p.pat_expiry, p.epc_expiry,
               c.id, c.name, c.phone, c.email, p.photo, p.tenant_email
        FROM properties p
        JOIN clients c ON p.client_id = c.id
        WHERE p.id = %s
    """, (property_id,))
    row = cur.fetchone()
    
    if not row:
        return "Property not found", 404

    prop = {
        'id': row[0], 'address': row[1], 'postcode': row[2], 'city': row[3],
        'tenant': row[4], 'tenant_phone': row[5], 'key_code': row[6],
        'gas': row[7], 'eicr': row[8], 'pat': row[9], 'epc': row[10],
        'photo': row[15], 'tenant_email': row[16]
    }
    client = {'id': row[11], 'name': row[12], 'phone': row[13], 'email': row[14]}

    # 2. Fetch Jobs & Attach Job-Specific Artifacts (Photos, RAMS, Certs, Invoices)
    cur.execute("""
        SELECT j.id, j.ref, j.status, j.description, j.start_date, q.job_title
        FROM jobs j 
        LEFT JOIN quotes q ON j.quote_id = q.id
        WHERE j.property_id = %s 
        ORDER BY 
            CASE WHEN j.start_date IS NULL THEN 1 ELSE 0 END,
            j.start_date DESC,
            j.created_at DESC
    """, (property_id,))
    raw_jobs = cur.fetchall()
    
    jobs = []
    for j in raw_jobs:
        job_id = j[0]
        raw_date = j[4]
        date_obj = None
        if raw_date:
            if isinstance(raw_date, (datetime, date)):
                date_obj = raw_date
            elif isinstance(raw_date, str):
                try:
                    date_obj = datetime.strptime(raw_date[:10], '%Y-%m-%d').date()
                except:
                    pass

        title = (j[5] or j[3] or f"Job {j[1]}").strip()

        # Fetch Evidence/Photos specifically tied to THIS job
        cur.execute("""
            SELECT id, filepath, uploaded_at, file_type, visible_to_client 
            FROM job_evidence 
            WHERE job_id = %s 
            ORDER BY uploaded_at DESC
        """, (job_id,))
        job_evidence_rows = cur.fetchall()
        
        job_photos = []
        job_certs = []
        for ev in job_evidence_rows:
            f_path = ev[1] if ev[1].startswith('/') else '/' + ev[1]
            f_type = ev[3] or 'Site Photo'
            if f_type in ['Site Photo', 'Photo', 'Progress Photo', 'Completion Photo']:
                job_photos.append({'id': ev[0], 'path': f_path, 'type': f_type, 'date': ev[2]})
            else:
                job_certs.append({'id': ev[0], 'path': f_path, 'type': f_type, 'date': ev[2]})

        # Fetch RAMS tied to THIS job
        cur.execute("""
            SELECT id, pdf_path, created_at 
            FROM job_rams 
            WHERE job_id = %s 
            ORDER BY created_at DESC LIMIT 1
        """, (job_id,))
        rams_row = cur.fetchone()
        job_rams = None
        if rams_row and rams_row[1]:
            job_rams = {'id': rams_row[0], 'path': rams_row[1], 'date': rams_row[2]}

        # Fetch Invoices tied to THIS job
        cur.execute("""
            SELECT id, reference, status, total, date 
            FROM invoices 
            WHERE job_id = %s AND status != 'Void'
            LIMIT 1
        """, (job_id,))
        inv_row = cur.fetchone()
        job_invoice = None
        if inv_row:
            job_invoice = {'id': inv_row[0], 'ref': inv_row[1], 'status': inv_row[2], 'total': float(inv_row[3] or 0), 'date': inv_row[4]}

        jobs.append({
            'id': job_id,
            'ref': j[1],
            'status': j[2],
            'desc': j[3] or '',
            'title': title,
            'date': date_obj,
            'photos': job_photos,
            'certs': job_certs,
            'rams': job_rams,
            'invoice': job_invoice
        })

    # 3. Fetch Permanent Property Documents (Blueprints, Lease, Deeds)
    cur.execute("""
        SELECT id, document_type, filepath, uploaded_at, visible_to_client 
        FROM property_documents 
        WHERE property_id = %s AND company_id = %s
        ORDER BY uploaded_at DESC
    """, (property_id, session.get('company_id')))
    
    prop_docs = []
    for d in cur.fetchall():
        prop_docs.append({'id': d[0], 'type': d[1], 'path': d[2], 'date': d[3], 'visible': d[4]})

    return render_template('office/property_details.html', prop=prop, client=client, jobs=jobs, prop_docs=prop_docs, today=date.today())

@client_bp.route('/office/client/<int:client_id>/mass-email', methods=['POST'])
def mass_email_tenants(client_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    subject = request.form.get('subject')
    message = request.form.get('message')
    
    conn = get_db(); cur = conn.cursor()
    try:
        # Get all properties for this client that have a tenant email
        cur.execute("""
            SELECT tenant_email 
            FROM properties 
            WHERE client_id = %s AND company_id = %s AND tenant_email IS NOT NULL AND tenant_email != ''
        """, (client_id, comp_id))
        
        emails = [row[0] for row in cur.fetchall()]
        
        if not emails:
            flash("No tenant emails found for this client.", "warning")
            return redirect(url_for('client.view_client', client_id=client_id))
            
        from tasks import send_tenant_email_task
        
        sent_count = 0
        for email in emails:
            # Send Email (via Celery)
            send_tenant_email_task.delay(
                company_id=comp_id,
                recipient_email=email,
                subject=subject,
                body_html=f"<p>{message}</p>"
            )
            sent_count += 1
            
        flash(f"✅ Mass email queued for {sent_count} tenants.", "success")
    except Exception as e:
        flash(f"Error: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('client.view_client', client_id=client_id))

@client_bp.route('/office/property/<int:property_id>/upload-document', methods=['POST'])
def upload_property_document(property_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    doc_type = request.form.get('document_type')
    visible_to_client = True if request.form.get('visible_to_client') == '1' else False
    
    conn = get_db(); cur = conn.cursor()
    try:
        from werkzeug.utils import secure_filename
        import os
        from flask import current_app
        
        if 'document' in request.files:
            file = request.files['document']
            if file and file.filename != '':
                from datetime import datetime
                relative_path = f"company_{comp_id}/property_documents"
                save_dir = os.path.join(current_app.static_folder, 'uploads', relative_path)
                os.makedirs(save_dir, exist_ok=True)
                
                filename = secure_filename(f"PROP_{property_id}_{int(datetime.now().timestamp())}_{file.filename}")
                file.save(os.path.join(save_dir, filename))
                
                db_path = f"/uploads/{relative_path}/{filename}"
                cur.execute("""
                    INSERT INTO property_documents (company_id, property_id, document_type, filepath, uploaded_by, visible_to_client) 
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (comp_id, property_id, doc_type, db_path, session['user_id'], visible_to_client))
                flash("📄 Document uploaded successfully.", "success")
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error uploading document: {e}", "error")
    finally:
        pass
        
    return redirect(request.referrer)

@client_bp.route('/office/property/delete-document/<int:doc_id>')
def delete_property_document(doc_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    try:
        # Fetch file path for deletion
        cur.execute("SELECT filepath FROM property_documents WHERE id = %s AND company_id = %s", (doc_id, session.get('company_id')))
        row = cur.fetchone()
        if row and row[0]:
            from utils.validators import delete_file_safely
            delete_file_safely(row[0])
            
        # Security check: ensure doc belongs to user's company
        cur.execute("DELETE FROM property_documents WHERE id = %s AND company_id = %s", (doc_id, session.get('company_id')))
        conn.commit()
        flash("🗑️ Document deleted.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        pass
    return redirect(request.referrer)

@client_bp.route('/office/property/update', methods=['POST'])
def update_property():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    prop_id = request.form.get('property_id')
    client_id = request.form.get('client_id')
    
    addr = request.form.get('address')
    post = request.form.get('postcode')
    tenant = request.form.get('tenant_name')
    t_phone = request.form.get('tenant_phone')
    t_email = request.form.get('tenant_email')
    key = request.form.get('key_code')
    
    gas = request.form.get('gas_expiry') or None
    eicr = request.form.get('eicr_expiry') or None
    pat = request.form.get('pat_expiry') or None
    epc = request.form.get('epc_expiry') or None
    
    photo_file = request.files.get('property_photo') or request.files.get('photo')
    new_photo = save_property_photo(photo_file, comp_id)
    
    conn = get_db(); cur = conn.cursor()
    try:
        if new_photo:
            cur.execute("""
                UPDATE properties 
                SET address_line1=%s, postcode=%s, tenant_name=%s, tenant_phone=%s, tenant_email=%s, key_code=%s,
                    gas_expiry=%s, eicr_expiry=%s, pat_expiry=%s, epc_expiry=%s, photo=%s
                WHERE id=%s
            """, (addr, post, tenant, t_phone, t_email, key, gas, eicr, pat, epc, new_photo, prop_id))
        else:
            cur.execute("""
                UPDATE properties 
                SET address_line1=%s, postcode=%s, tenant_name=%s, tenant_phone=%s, tenant_email=%s, key_code=%s,
                    gas_expiry=%s, eicr_expiry=%s, pat_expiry=%s, epc_expiry=%s
                WHERE id=%s
            """, (addr, post, tenant, t_phone, t_email, key, gas, eicr, pat, epc, prop_id))
        conn.commit()
        flash("✅ Property updated successfully.")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('client.view_client', client_id=client_id) if client_id else request.referrer)

# =========================================================
# 4. APIs & UTILITIES
# =========================================================

@client_bp.route('/api/client/<int:client_id>/properties')
def get_client_properties(client_id):
    if 'user_id' not in session: return jsonify([])
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT id, address_line1, postcode 
        FROM properties 
        WHERE client_id = %s AND company_id = %s
        ORDER BY address_line1 ASC
    """, (client_id, session.get('company_id')))
    
    props = [{'id': r[0], 'address': f"{r[1]} {r[2] or ''}"} for r in cur.fetchall()]
    pass
    return jsonify(props)

@client_bp.route('/client/<int:client_id>/reset-password', methods=['POST'])
def reset_client_password(client_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    try:
        # Verify client and ensure they have portal access
        cur.execute("SELECT name, email, portal_access FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
        client_row = cur.fetchone()
        
        if not client_row:
            flash("Client not found.", "error")
            return redirect(url_for('client.client_dashboard'))
            
        client_name, client_email, portal_access = client_row
        
        if not portal_access:
            flash("Cannot reset password: This client does not have Portal Access enabled.", "error")
            return redirect(url_for('client.view_client', client_id=client_id))
            
        if not client_email:
            flash("Cannot reset password: This client does not have an email address on file.", "error")
            return redirect(url_for('client.view_client', client_id=client_id))

        from werkzeug.security import generate_password_hash
        import secrets
        import string
        from tasks import send_client_portal_invite_task
        
        # Generate new password
        alphabet = string.ascii_letters + string.digits
        temp_pass = ''.join(secrets.choice(alphabet) for i in range(10))
        hashed_pass = generate_password_hash(temp_pass)
        
        # Update DB
        cur.execute("UPDATE clients SET password_hash = %s WHERE id = %s AND company_id = %s", (hashed_pass, client_id, comp_id))
        
        # Fetch company details for email
        cur.execute("SELECT COALESCE(sub_domain, subdomain), name FROM companies WHERE id = %s", (comp_id,))
        comp_row = cur.fetchone()
        
        conn.commit()
        
        if comp_row and comp_row[0]:
            subdomain = comp_row[0]
            company_name = comp_row[1]
            portal_url = f"https://{subdomain}.businessbetter.co.uk/portal/login/{comp_id}"
            
            send_client_portal_invite_task.delay(
                company_id=comp_id,
                client_email=client_email,
                client_name=client_name,
                temp_pass=temp_pass,
                portal_url=portal_url,
                company_name=company_name
            )
            flash(f"✅ Password regenerated. A new login email has been sent to {client_email}.", "success")
        else:
            flash("Password updated, but could not send email (missing company details).", "warning")

    except Exception as e:
        conn.rollback()
        flash(f"Error resetting password: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('client.view_client', client_id=client_id))


@client_bp.route('/client/delete/<int:client_id>')
def delete_client(client_id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("UPDATE clients SET status='Archived' WHERE id=%s AND company_id=%s", (client_id, session.get('company_id')))
        conn.commit()
        flash("🗑️ Client archived.")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}")
    finally:
        pass
    return redirect(url_for('client.client_dashboard'))

@client_bp.route('/track/<job_ref>')
def track_job(job_ref):
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT 
            j.id, j.status, j.start_date, j.site_address,
            s.name, s.position, s.profile_photo,
            v.tracker_url,
            j.company_id
        FROM jobs j
        LEFT JOIN staff s ON j.engineer_id = s.id
        LEFT JOIN vehicles v ON j.vehicle_id = v.id
        WHERE j.ref = %s
    """, (job_ref,))
    
    row = cur.fetchone()
    if not row: return "Job not found", 404

    job_data = {
        'ref': job_ref, 'status': row[1], 'start_date': row[2],
        'site_lat': 51.5074, 'site_lon': -0.1278
    }
    
    engineer_data = {
        'name': row[4] or "Assigned Engineer",
        'position': row[5] or "Technician",
        'photo': row[6]
    }
    
    tracker_url = row[7]
    comp_id = row[8]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {r[0]: r[1] for r in cur.fetchall()}

    telematics = None
    if tracker_url and get_tracker_data:
        api_key = settings.get('samsara_api_key')
        telematics = get_tracker_data(tracker_url, api_key=api_key)

    pass
    return render_template('public/track_job.html', job=job_data, engineer=engineer_data, telematics=telematics, settings=settings)