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
        SELECT id, name, email, phone, site_address, status, gate_code, billing_address, notes 
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
    
    # Check limits if function exists
    allowed, msg = check_limit(comp_id, 'max_clients')
    if not allowed:
        flash(msg, "error")
        return redirect(url_for('client.client_dashboard'))

    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    addr = request.form.get('address')
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, site_address, billing_address, status)
            VALUES (%s, %s, %s, %s, %s, %s, 'Active')
            RETURNING id
        """, (comp_id, name, email, phone, addr, addr))
        new_id = cur.fetchone()[0]
        
        # Auto-create first property (Site Address)
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1)
            VALUES (%s, %s, %s)
        """, (comp_id, new_id, addr))
        
        conn.commit()
        flash("✅ Client Added")
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
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
    conn = get_db(); cur = conn.cursor()
    
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
    
    conn.close()
    
    return render_template('office/client_details.html', 
                           client=client, 
                           properties=properties, 
                           invoices=invoices,
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
    key = request.form.get('key_code')
    
    gas = request.form.get('gas_expiry') or None
    eicr = request.form.get('eicr_expiry') or None
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, tenant_name, tenant_phone, key_code, gas_expiry, eicr_expiry)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, addr, post, tenant, t_phone, key, gas, eicr))
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

    # 2. Fetch Jobs
    cur.execute("""
        SELECT id, ref, status, description, start_date 
        FROM jobs 
        WHERE property_id = %s 
        ORDER BY start_date DESC
    """, (property_id,))
    jobs = []
    for j in cur.fetchall():
        jobs.append({'id': j[0], 'ref': j[1], 'status': j[2], 'desc': j[3], 'date': j[4]})

    # 3. Fetch Certificates (FIXED: Using job_evidence and filepath)
    # The error 'relation job_files does not exist' happened here.
    # We now point to job_evidence and check for file_type or generic photos.
    cur.execute("""
        SELECT f.id, f.file_type, f.uploaded_at, j.ref, f.filepath
        FROM job_evidence f
        JOIN jobs j ON f.job_id = j.id
        WHERE j.property_id = %s
        ORDER BY f.uploaded_at DESC
    """, (property_id,))
    
    certs = []
    for c in cur.fetchall():
        # c[1] is file_type (e.g. 'CP12', 'EICR', or 'Site Photo')
        # c[4] is filepath
        certs.append({'type': c[1], 'date': c[2], 'job_ref': c[3], 'path': c[4]})

    conn.close()
    
    return render_template('office/property_details.html', prop=prop, client=client, jobs=jobs, certs=certs, today=date.today())

@client_bp.route('/office/property/update', methods=['POST'])
def update_property():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    prop_id = request.form.get('property_id')
    client_id = request.form.get('client_id')
    
    addr = request.form.get('address')
    post = request.form.get('postcode')
    tenant = request.form.get('tenant_name')
    t_phone = request.form.get('tenant_phone')
    key = request.form.get('key_code')
    
    gas = request.form.get('gas_expiry') or None
    eicr = request.form.get('eicr_expiry') or None
    pat = request.form.get('pat_expiry') or None
    epc = request.form.get('epc_expiry') or None
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE properties 
            SET address_line1=%s, postcode=%s, tenant_name=%s, tenant_phone=%s, key_code=%s,
                gas_expiry=%s, eicr_expiry=%s, pat_expiry=%s, epc_expiry=%s
            WHERE id=%s
        """, (addr, post, tenant, t_phone, key, gas, eicr, pat, epc, prop_id))
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