from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from db import get_db, get_site_config
from datetime import date, datetime

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

    cur.execute("""
        SELECT id, name, email, phone, site_address, status, gate_code, billing_address, notes, portal_access 
        FROM clients WHERE company_id = %s ORDER BY name ASC
    """, (comp_id,))
    clients = cur.fetchall()
    conn.close()
    
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
    
    # FIX: Get the correct field name from your HTML form
    billing_addr = request.form.get('billing_address')
    portal_access = 1 if request.form.get('portal_access') == 'on' else 0

    # LOGIC: If address is empty, set a placeholder so DB doesn't crash
    safe_addr = billing_addr if billing_addr and billing_addr.strip() else "Address Pending"
    
    conn = get_db(); cur = conn.cursor()
    try:
        from werkzeug.security import generate_password_hash
        import secrets
        import string
        from tasks import send_client_portal_invite_task
        
        hashed_pass = None
        temp_pass = None
        
        if portal_access == 1:
            # Generate secure random password
            alphabet = string.ascii_letters + string.digits
            temp_pass = ''.join(secrets.choice(alphabet) for i in range(10))
            hashed_pass = generate_password_hash(temp_pass)

        # 1. Create Client (using billing_address & password_hash)
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, billing_address, status, password_hash, portal_access)
            VALUES (%s, %s, %s, %s, %s, 'Active', %s, %s)
            RETURNING id
        """, (comp_id, name, email, phone, safe_addr, hashed_pass, portal_access))
        new_id = cur.fetchone()[0]
        
        # 2. Create First Property (using the same address as the 'Site Address')
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, type, status)
            VALUES (%s, %s, %s, '', 'Property', 'Active')
        """, (comp_id, new_id, safe_addr))
        
        # 3. Fetch Company Details to construct the portal URL
        cur.execute("SELECT COALESCE(sub_domain, subdomain), name FROM companies WHERE id = %s", (comp_id,))
        comp_row = cur.fetchone()
        
        conn.commit()
        flash("✅ Client Added")
        
        # 4. Trigger the background email task if portal access is enabled
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

    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
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

    conn = get_db(); cur = conn.cursor()
    try:
        # Check current portal access to see if it's being toggled ON
        cur.execute("SELECT portal_access, password_hash FROM clients WHERE id = %s AND company_id = %s", (client_id, comp_id))
        row = cur.fetchone()
        
        needs_password = False
        temp_pass = None
        hashed_pass = None

        if row:
            current_access = row[0]
            has_password = bool(row[1])
            
            # If they are enabling portal access and it was disabled OR they have no password yet
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
                    name=%s, email=%s, phone=%s, status=%s, billing_address=%s, notes=%s, portal_access=%s, password_hash=%s
                WHERE id=%s AND company_id=%s
            """, (name, email, phone, status, billing_address, notes, portal_access, hashed_pass, client_id, comp_id))
            
            # Fetch Company Details to construct the portal URL
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
                    name=%s, email=%s, phone=%s, status=%s, billing_address=%s, notes=%s, portal_access=%s
                WHERE id=%s AND company_id=%s
            """, (name, email, phone, status, billing_address, notes, portal_access, client_id, comp_id))
            flash("✅ Client updated successfully.")

        conn.commit()
    except Exception as e:
        conn.rollback(); flash(f"Error updating client: {e}", "error")
    finally:
        conn.close()
        
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
    
    # ✅ SECURITY FIX: Verify client belongs to user's company
    cur.execute("SELECT company_id FROM clients WHERE id = %s", (client_id,))
    client_row = cur.fetchone()
    if not client_row or client_row[0] != comp_id:
        conn.close()
        return "Unauthorized: Client not found or belongs to different company", 403
    
    
    # 1. Fetch Client Details (With Billing & Notes)
    cur.execute("""
        SELECT id, name, email, phone, billing_address, notes 
        FROM clients 
        WHERE id = %s AND company_id = %s
    """, (client_id, comp_id))
    client_row = cur.fetchone()
    
    if not client_row:
        conn.close()
        return "Client not found", 404

    client = {
        'id': client_row[0], 'name': client_row[1], 'email': client_row[2], 
        'phone': client_row[3], 'billing_address': client_row[4], 'notes': client_row[5]
    }

    # 2. Fetch Properties
    cur.execute("""
        SELECT id, address_line1, postcode, city, tenant_name, tenant_phone, 
               key_code, gas_expiry, eicr_expiry, pat_expiry, epc_expiry
        FROM properties 
        WHERE client_id = %s 
        ORDER BY address_line1
    """, (client_id,))
    
    properties = []
    cols = ['id', 'address_line1', 'postcode', 'city', 'tenant_name', 'tenant_phone', 
            'key_code', 'gas_expiry', 'eicr_expiry', 'pat_expiry', 'epc_expiry']
            
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
    
    conn.close()
    
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
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, tenant_name, tenant_phone, tenant_email, key_code, gas_expiry, eicr_expiry)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, addr, post, tenant, t_phone, t_email, key, gas, eicr))
        conn.commit()
        flash("✅ Property added.")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
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
               c.id, c.name, c.phone, c.email
        FROM properties p
        JOIN clients c ON p.client_id = c.id
        WHERE p.id = %s
    """, (property_id,))
    row = cur.fetchone()
    
    if not row:
        conn.close()
        return "Property not found", 404

    prop = {
        'id': row[0], 'address': row[1], 'postcode': row[2], 'city': row[3],
        'tenant': row[4], 'tenant_phone': row[5], 'key_code': row[6],
        'gas': row[7], 'eicr': row[8], 'pat': row[9], 'epc': row[10]
    }
    client = {'id': row[11], 'name': row[12], 'phone': row[13], 'email': row[14]}

    # 2. Fetch Jobs (With Date Fixing)
    cur.execute("""
        SELECT id, ref, status, description, start_date 
        FROM jobs 
        WHERE property_id = %s 
        ORDER BY start_date DESC
    """, (property_id,))
    
    jobs = []
    for j in cur.fetchall():
        # --- THE FIX: Convert Text Date to Date Object ---
        raw_date = j[4]
        date_obj = None
        if raw_date:
            if isinstance(raw_date, str):
                try:
                    # Try timestamp format first (e.g. 2025-01-19 14:30:00)
                    safe_str = raw_date.split('.')[0] # Remove milliseconds if present
                    date_obj = datetime.strptime(safe_str, '%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    try:
                        # Try simple date format (e.g. 2025-01-19)
                        date_obj = datetime.strptime(raw_date, '%Y-%m-%d')
                    except:
                        pass # Keep as None if fail
            else:
                date_obj = raw_date # Already an object

        jobs.append({'id': j[0], 'ref': j[1], 'status': j[2], 'desc': j[3], 'date': date_obj})

    # 3. Fetch Certificates (Fixed for job_evidence)
    cur.execute("""
        SELECT f.id, f.file_type, f.uploaded_at, j.ref, f.filepath
        FROM job_evidence f
        JOIN jobs j ON f.job_id = j.id
        WHERE j.property_id = %s
        ORDER BY f.uploaded_at DESC
    """, (property_id,))
    
    certs = []
    for c in cur.fetchall():
        certs.append({'type': c[1], 'date': c[2], 'job_ref': c[3], 'path': c[4]})

    conn.close()
    
    return render_template('office/property_details.html', prop=prop, client=client, jobs=jobs, certs=certs, today=date.today())

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
        conn.close()
        
    return redirect(url_for('client.view_client', client_id=client_id))

@client_bp.route('/office/property/update', methods=['POST'])
def update_property():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
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
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE properties 
            SET address_line1=%s, postcode=%s, tenant_name=%s, tenant_phone=%s, tenant_email=%s, key_code=%s,
                gas_expiry=%s, eicr_expiry=%s, pat_expiry=%s, epc_expiry=%s
            WHERE id=%s
        """, (addr, post, tenant, t_phone, t_email, key, gas, eicr, pat, epc, prop_id))
        conn.commit()
        flash("✅ Property updated.")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('client.view_client', client_id=client_id))

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
    conn.close()
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
        conn.close()
        
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
        conn.close()
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

    conn.close()
    return render_template('public/track_job.html', job=job_data, engineer=engineer_data, telematics=telematics, settings=settings)