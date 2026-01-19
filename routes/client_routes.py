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