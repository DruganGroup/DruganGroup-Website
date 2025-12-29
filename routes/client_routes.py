from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from db import get_db, get_site_config

client_bp = Blueprint('client', __name__)

@client_bp.route('/clients')
def client_dashboard():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

    # 1. Create the Smart Client Table
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS clients (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                billing_address TEXT,
                site_address TEXT,
                gate_code TEXT,
                notes TEXT,
                status TEXT DEFAULT 'Active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.commit()
    except:
        conn.rollback()

    # 2. Fetch Clients (Alphabetical)
    cur.execute("SELECT id, name, email, phone, site_address, status, gate_code, billing_address, notes FROM clients WHERE company_id = %s ORDER BY name ASC", (comp_id,))
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
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    billing = request.form.get('billing_address')
    site = request.form.get('site_address')
    # If Site Address is left empty, assume it's same as Billing
    if not site: site = billing
        
    code = request.form.get('gate_code')
    notes = request.form.get('notes')
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, billing_address, site_address, gate_code, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, name, email, phone, billing, site, code, notes))
        conn.commit()
        flash(f"✅ Client '{name}' added successfully")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error adding client: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('client.client_dashboard'))

@client_bp.route('/clients/update', methods=['POST'])
def update_client():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
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
            UPDATE clients 
            SET name=%s, email=%s, phone=%s, billing_address=%s, site_address=%s, gate_code=%s, notes=%s, status=%s
            WHERE id=%s AND company_id=%s
        """, (name, email, phone, billing, site, code, notes, status, client_id, session.get('company_id')))
        conn.commit()
        flash("✅ Client details updated")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error updating client: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('client.client_dashboard'))

@client_bp.route('/clients/delete/<int:id>')
def delete_client(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("DELETE FROM clients WHERE id=%s AND company_id=%s", (id, session.get('company_id')))
    conn.commit(); conn.close()
    return redirect(url_for('client.client_dashboard'))