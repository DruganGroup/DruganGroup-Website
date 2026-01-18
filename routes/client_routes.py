from flask import Blueprint, render_template, session, redirect, url_for, request, flash, jsonify
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