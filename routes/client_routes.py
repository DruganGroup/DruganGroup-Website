from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from db import get_db, get_site_config
from services.enforcement import check_limit
from email_service import send_company_email
import random
import string
from werkzeug.security import generate_password_hash
from datetime import date

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

# --- 2. OFFICE VIEW: ADD NEW CLIENT ---
@client_bp.route('/clients/add', methods=['POST'])
def add_client():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: 
        return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')

    # --- CHECK LIMIT (INDENTED CORRECTLY) ---
    allowed, msg = check_limit(comp_id, 'max_clients')
    if not allowed:
        flash(msg, "error")
        return redirect(url_for('client.client_dashboard'))
    # ----------------------------------------
    
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    billing = request.form.get('billing_address')
    site = request.form.get('site_address') or billing
    code = request.form.get('gate_code')
    notes = request.form.get('notes')
    
    raw_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    hashed_password = generate_password_hash(raw_password)
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, billing_address, site_address, gate_code, notes, password_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
        """, (comp_id, name, email, phone, billing, site, code, notes, hashed_password))
        
        if email:
            cur.execute("SELECT name FROM companies WHERE id = %s", (comp_id,))
            company_name = cur.fetchone()[0]
            subject = f"Welcome to the {company_name} Client Portal"
            body = f"""
            <h3>Welcome, {name}</h3>
            <p>{company_name} has created your secure portal.</p>
            <p><strong>Login:</strong> <a href='https://www.businessbetter.co.uk/portal/login'>Click Here</a></p>
            <p><strong>Username:</strong> {email}<br><strong>Password:</strong> {raw_password}</p>
            """
            send_company_email(comp_id, email, subject, body)
            
        conn.commit()
        flash(f"✅ Client '{name}' added and invited.")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('client.client_dashboard'))

# --- 3. OFFICE VIEW: UPDATE CLIENT ---
@client_bp.route('/clients/update', methods=['POST'])
def update_client():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: 
        return redirect(url_for('auth.login'))
    
    client_id = request.form.get('client_id')
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    billing = request.form.get('billing_address')
    site = request.form.get('site_address')
    code = request.form.get('gate_code')
    notes = request.form.get('notes')
    status = request.form.get('status')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE clients SET name=%s, email=%s, phone=%s, billing_address=%s, 
            site_address=%s, gate_code=%s, notes=%s, status=%s
            WHERE id=%s AND company_id=%s
        """, (name, email, phone, billing, site, code, notes, status, client_id, session.get('company_id')))
        conn.commit()
        flash("✅ Client details updated")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
    return redirect(url_for('client.client_dashboard'))

# --- 4. OFFICE VIEW: DELETE CLIENT ---
@client_bp.route('/clients/delete/<int:id>')
def delete_client(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('client.client_dashboard'))

# --- 5. OFFICE VIEW: INDIVIDUAL CLIENT PROFILE ---
@client_bp.route('/client/<int:client_id>')
def view_client(client_id):
    if session.get('role') not in ['Admin', 'Office', 'Manager', 'SuperAdmin']: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM clients WHERE id = %s AND company_id = %s", (client_id, session['company_id']))
    client = cur.fetchone()
    
    if not client:
        conn.close()
        return "Client not found", 404
        
    cur.execute("""
        SELECT id, address_line1, postcode, tenant_name, 
               gas_safety_due, eicr_due, pat_test_due, fire_risk_due, epc_expiry, tenant_phone
        FROM properties WHERE client_id = %s ORDER BY id DESC
    """, (client_id,))
    
    raw_props = cur.fetchall()
    properties = []
    today = date.today()

    def get_status(d):
        if not d: return 'Missing'
        if d < today: return 'Expired'
        if (d - today).days <= 30: return 'Due'
        return 'Valid'

    for p in raw_props:
        properties.append({
            'id': p[0], 'addr': p[1], 'postcode': p[2], 'tenant': p[3], 'tenant_phone': p[9],
            'compliance': {
                'Gas': {'date': p[4], 'status': get_status(p[4])},
                'EICR': {'date': p[5], 'status': get_status(p[5])},
                'PAT': {'date': p[6], 'status': get_status(p[6])},
                'Fire': {'date': p[7], 'status': get_status(p[7])},
                'EPC': {'date': p[8], 'status': get_status(p[8])}
            }
        })
    
    conn.close()
    
    client_data = {
        'id': client[0], 'name': client[2], 'email': client[3],
        'phone': client[4], 'addr': client[5] or client[6] 
    }
    
    return render_template('office/client_details.html', client=client_data, properties=properties)

# --- 6. OFFICE VIEW: ADD PROPERTY (WITH COMPLIANCE DATES) ---
@client_bp.route('/client/<int:client_id>/add-property', methods=['POST'])
def add_property(client_id):
    if session.get('role') not in ['Admin', 'Office', 'Manager', 'SuperAdmin']: return "Access Denied"
    
    # --- CHECK LIMIT (INDENTED CORRECTLY) ---
    allowed, msg = check_limit(session['company_id'], 'max_properties')
    if not allowed:
        flash(msg, "error")
        return redirect(url_for('client.view_client', client_id=client_id))
    # ----------------------------------------
    
    conn = get_db()
    cur = conn.cursor()
    try:
        address1 = request.form.get('address_line1')
        postcode = request.form.get('postcode')
        gas_due = request.form.get('gas_safety_due') or None
        eicr_due = request.form.get('eicr_due') or None
        pat_due = request.form.get('pat_test_due') or None
        fire_due = request.form.get('fire_risk_due') or None
        epc_due = request.form.get('epc_expiry') or None

        cur.execute("""
            INSERT INTO properties 
            (company_id, client_id, address_line1, postcode, 
             gas_safety_due, eicr_due, pat_test_due, fire_risk_due, epc_expiry)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            session['company_id'], client_id, address1, postcode,
            gas_due, eicr_due, pat_due, fire_due, epc_due
        ))
        conn.commit()
        flash("✅ Property & Compliance Dates Saved")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('client.view_client', client_id=client_id))

# --- 7. PORTAL: CLIENT ADDS THEIR OWN PROPERTY ---
@client_bp.route('/portal/add-property', methods=['POST'])
def portal_add_property():
    if 'client_id' not in session: return redirect(url_for('auth.client_portal_login'))
    
    client_id, comp_id = session.get('client_id'), session.get('company_id')
    
    # --- CHECK LIMIT (SECURITY FIX) ---
    # Even though it's the client adding it, it belongs to the company's quota.
    allowed, msg = check_limit(comp_id, 'max_properties')
    if not allowed:
        flash("❌ Cannot add property: The management company has reached their property limit.", "error")
        return redirect(url_for('client.client_portal_home'))
    # ----------------------------------

    address = request.form.get('address')
    tenant = request.form.get('tenant_name')
    phone = request.form.get('tenant_phone')
    access = request.form.get('access_info')
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO properties (client_id, company_id, address_line1, tenant_name, tenant_phone, access_info) 
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (client_id, comp_id, address, tenant, phone, access))
    conn.commit(); conn.close()
    flash("✅ Property added to your dashboard.")
    return redirect(url_for('client.client_portal_home'))

# --- 8. PORTAL: CLIENT RAISES SERVICE REQUEST ---
@client_bp.route('/portal/raise-issue', methods=['POST'])
def raise_issue():
    if 'client_id' not in session: return redirect(url_for('auth.client_portal_login'))
    
    client_id, comp_id = session.get('client_id'), session.get('company_id')
    prop_id = request.form.get('property_id')
    desc = request.form.get('description')
    sev = request.form.get('severity')
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        INSERT INTO service_requests (property_id, client_id, company_id, issue_description, severity) 
        VALUES (%s, %s, %s, %s, %s)
    """, (prop_id, client_id, comp_id, desc, sev))
    conn.commit(); conn.close()
    flash("🚨 Issue reported to the office.")
    return redirect(url_for('client.client_portal_home'))

# --- 9. PORTAL: CLIENT HOME DASHBOARD ---
@client_bp.route('/portal/home')
def client_portal_home():
    if 'client_id' not in session: return redirect(url_for('auth.client_portal_login'))
    
    comp_id, client_id = session.get('company_id'), session.get('client_id')
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, client_id, company_id, address_line1, tenant_name, tenant_phone, access_info FROM properties WHERE client_id = %s", (client_id,))
    properties = cur.fetchall()
    
    cur.execute("""
        SELECT r.id, p.address_line1, r.property_id, r.client_id, r.issue_description, r.severity, r.status, r.created_at 
        FROM service_requests r 
        JOIN properties p ON r.property_id = p.id 
        WHERE r.client_id = %s ORDER BY r.created_at DESC
    """, (client_id,))
    requests = cur.fetchall()
    conn.close()
    
    return render_template('clients/portal_home.html', 
                           client_name=session.get('client_name'), 
                           properties=properties, 
                           requests=requests, 
                           brand_color=config['color'], 
                           logo_url=config['logo'])

# --- 10. DATABASE REPAIR TOOL (ENHANCED) ---
@client_bp.route('/clients/fix-schema')
def fix_client_schema():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS password_hash TEXT;")
        cur.execute("""CREATE TABLE IF NOT EXISTS properties (
            id SERIAL PRIMARY KEY, 
            client_id INTEGER REFERENCES clients(id) ON DELETE CASCADE,
            company_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);""")

        cur.execute("""
            DO $$ 
            BEGIN 
                IF EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='properties' AND column_name='address') THEN
                    ALTER TABLE properties RENAME COLUMN address TO address_line1;
                END IF;
            END $$;
        """)

        columns_to_add = [
            ("address_line1", "TEXT"),
            ("postcode", "TEXT"),
            ("tenant_name", "TEXT"),
            ("tenant_phone", "TEXT"),
            ("access_info", "TEXT"),
            ("gas_safety_due", "DATE"),
            ("eicr_due", "DATE"),
            ("pat_test_due", "DATE"),
            ("fire_risk_due", "DATE"),
            ("epc_expiry", "DATE")
        ]

        for col_name, col_type in columns_to_add:
            try:
                cur.execute(f"ALTER TABLE properties ADD COLUMN IF NOT EXISTS {col_name} {col_type};")
            except Exception as e:
                print(f"Skipping {col_name}: {e}")

        cur.execute("""CREATE TABLE IF NOT EXISTS service_requests (
            id SERIAL PRIMARY KEY, 
            property_id INTEGER REFERENCES properties(id) ON DELETE CASCADE,
            client_id INTEGER, 
            company_id INTEGER, 
            issue_description TEXT, 
            severity TEXT, 
            status TEXT DEFAULT 'Pending', 
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);""")
            
        conn.commit()
        return "✅ Database Refurbished: 'address' renamed to 'address_line1' and compliance dates ready."
    except Exception as e: 
        conn.rollback()
        return f"❌ Migration Error: {e}"
    finally: 
        conn.close()