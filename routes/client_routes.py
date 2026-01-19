from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
from db import get_db, get_site_config
from services.enforcement import check_limit
from email_service import send_company_email
import random
import string
from werkzeug.security import generate_password_hash
from datetime import date
try:
    from telematics_engine import get_tracker_data
except ImportError:
    get_tracker_data = None

client_bp = Blueprint('client', __name__)

# --- 1. OFFICE VIEW: LIST ALL CLIENTS ---
@client_bp.route('/clients')
def client_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

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

# --- API: GET PROPERTIES FOR DROPDOWN (FIXED) ---
@client_bp.route('/api/client/<int:client_id>/properties')
def get_client_properties(client_id):
    if 'user_id' not in session: return jsonify([])
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        SELECT id, address_line1, postcode 
        FROM properties 
        WHERE client_id = %s AND company_id = %s
        ORDER BY address_line1 ASC
    """, (client_id, session.get('company_id')))
    
    props = [{'id': r[0], 'address': f"{r[1]} {r[2] or ''}"} for r in cur.fetchall()]
    conn.close()
    
    return jsonify(props)
    
@client_bp.route('/track/<job_ref>')
def track_job(job_ref):
    """
    Public tracking page for customers.
    """
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Fetch Job & Engineer Details
    # We join Job -> Staff (Engineer) -> Vehicle -> Company Settings
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
    if not row:
        return "Job not found", 404

    # 2. Organize Data
    job_data = {
        'ref': job_ref,
        'status': row[1],
        'start_date': row[2],
        'site_lat': 51.5074, # In a real app, geocode the address row[3]
        'site_lon': -0.1278
    }
    
    engineer_data = {
        'name': row[4] or "Assigned Engineer",
        'position': row[5] or "Technician",
        'photo': row[6]
    }
    
    tracker_url = row[7]
    comp_id = row[8]

    # 3. Get Company Settings (Phone Number/API Keys)
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {r[0]: r[1] for r in cur.fetchall()}

    # 4. Fetch Live Telematics (If available)
    telematics = None
    if tracker_url and get_tracker_data:
        api_key = settings.get('samsara_api_key')
        telematics = get_tracker_data(tracker_url, api_key=api_key)

    conn.close()

    return render_template('public/track_job.html', 
                           job=job_data, 
                           engineer=engineer_data,
                           telematics=telematics,
                           settings=settings)
                           
@client_bp.route('/client/<int:client_id>')
def view_client(client_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Client Details (Including Billing Address & Notes)
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
        'id': client_row[0], 
        'name': client_row[1], 
        'email': client_row[2], 
        'phone': client_row[3],
        'billing_address': client_row[4], 
        'notes': client_row[5]
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
    
    # This loads the HTML file you uploaded earlier
    return render_template('office/client_details.html', 
                           client=client, 
                           properties=properties, 
                           invoices=invoices,
                           current_date=date.today())

# --- MISSING ROUTE 3: DELETE CLIENT ---
@client_bp.route('/client/delete/<int:client_id>')
def delete_client(client_id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("UPDATE clients SET status='Archived' WHERE id=%s AND company_id=%s", (client_id, session.get('company_id')))
        conn.commit()
        flash("🗑️ Client archived.")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('client.client_dashboard'))

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

    # 3. Fetch Certificates (The missing link)
    # We look for files in job_files that match certificate types
    cur.execute("""
        SELECT f.id, f.file_type, f.uploaded_at, j.ref, f.file_path
        FROM job_files f
        JOIN jobs j ON f.job_id = j.id
        WHERE j.property_id = %s AND f.file_type IN ('CP12', 'EICR', 'PAT', 'EPC')
        ORDER BY f.uploaded_at DESC
    """, (property_id,))
    certs = []
    for c in cur.fetchall():
        certs.append({'type': c[1], 'date': c[2], 'job_ref': c[3], 'path': c[4]})

    conn.close()
    
    # We will save your uploaded file as 'property_details.html'
    return render_template('office/property_details.html', prop=prop, client=client, jobs=jobs, certs=certs, today=date.today())

@client_bp.route('/office/property/update', methods=['POST'])
def update_property():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    prop_id = request.form.get('property_id')
    client_id = request.form.get('client_id')
    
    # Fields
    addr = request.form.get('address')
    post = request.form.get('postcode')
    tenant = request.form.get('tenant_name')
    t_phone = request.form.get('tenant_phone') # <--- Added
    key = request.form.get('key_code')
    
    # Dates
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

# --- 6. ADD PROPERTY (Fixed Tenant Phone) ---
@client_bp.route('/office/client/<int:client_id>/add-property', methods=['POST'])
def add_property(client_id):
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    addr = request.form.get('address')
    post = request.form.get('postcode')
    tenant = request.form.get('tenant_name')
    t_phone = request.form.get('tenant_phone') # <--- Added
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
    
# --- PASTE THIS INTO YOUR FLASK APP ---
@app.route('/debug/schema')
def debug_schema():
    # Only allow Admin/SuperAdmin to see this for security
    if session.get('role') not in ['Admin', 'SuperAdmin']:
        return "Unauthorized", 403

    conn = get_db()
    cur = conn.cursor()
    output = []

    try:
        # 1. Get ALL Table Names
        cur.execute("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """)
        tables = [r[0] for r in cur.fetchall()]

        output.append(f"FOUND {len(tables)} TABLES:\n")

        # 2. Loop Through Each Table and Get Columns
        for table in tables:
            output.append(f"==========================================")
            output.append(f"TABLE: {table}")
            output.append(f"==========================================")
            
            cur.execute(f"""
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns 
                WHERE table_name = '{table}'
                ORDER BY ordinal_position
            """)
            columns = cur.fetchall()
            
            for col in columns:
                # Format:  - column_name (type) [NULL/NOT NULL]
                nullable = "NULL" if col[2] == 'YES' else "NOT NULL"
                output.append(f"   - {col[0]} ({col[1]}) [{nullable}]")
            
            output.append("\n")

    except Exception as e:
        output.append(f"\nCRITICAL ERROR: {e}")
    finally:
        conn.close()

    # Print as plain text in browser
    return "<pre>" + "\n".join(output) + "</pre>"