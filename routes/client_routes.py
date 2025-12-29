from flask import Blueprint, render_template, session, redirect, url_for, request, flash
from db import get_db, get_site_config
from email_service import send_company_email
import random
import string
from werkzeug.security import generate_password_hash

client_bp = Blueprint('client', __name__)

@client_bp.route('/clients')
def client_dashboard():
    # Security: Allow Office/Admin roles
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Office']: return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db()
    cur = conn.cursor()

    # Fetch Clients
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
    name = request.form.get('name')
    email = request.form.get('email')
    phone = request.form.get('phone')
    billing = request.form.get('billing_address')
    site = request.form.get('site_address')
    if not site: site = billing # Fallback
        
    code = request.form.get('gate_code')
    notes = request.form.get('notes')
    
    # --- 1. GENERATE RANDOM PASSWORD ---
    # Create an 8-digit random password (letters + numbers)
    raw_password = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
    hashed_password = generate_password_hash(raw_password)
    
    conn = get_db()
    cur = conn.cursor()
    try:
        # --- 2. INSERT INTO DATABASE (With Password Hash) ---
        cur.execute("""
            INSERT INTO clients (company_id, name, email, phone, billing_address, site_address, gate_code, notes, password_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (comp_id, name, email, phone, billing, site, code, notes, hashed_password))
        
        new_client_id = cur.fetchone()[0]
        
        # --- 3. SEND WELCOME EMAIL ---
        if email:
            # We fetch the Company Name to make the email look professional
            cur.execute("SELECT name FROM companies WHERE id = %s", (comp_id,))
            company_name = cur.fetchone()[0]
            
            subject = f"Welcome to the {company_name} Client Portal"
            body = f"""
            <h3>Welcome, {name}</h3>
            <p>{company_name} has created a secure portal for you to view quotes and invoices.</p>
            <p><strong>Your Login Details:</strong></p>
            <ul>
                <li><strong>Username:</strong> {email}</li>
                <li><strong>Password:</strong> {raw_password}</li>
            </ul>
            <p>You can log in here: <a href="https://www.drugangroup.co.uk/portal/login">Client Login</a></p>
            <br>
            <p>Please keep these details safe.</p>
            """
            
            # Send the email
            send_company_email(comp_id, email, subject, body)
            flash(f"✅ Client Added! Welcome email sent to {email}")
        else:
            flash(f"✅ Client Added (No email provided, so no login sent).")

        conn.commit()
        
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

# --- DATABASE REPAIR TOOL (V2) ---
@client_bp.route('/clients/fix-schema')
def fix_client_schema():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Access Denied"
    
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS site_address TEXT;")
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS gate_code TEXT;")
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS billing_address TEXT;")
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS notes TEXT;")
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Active';")
        cur.execute("ALTER TABLE clients ADD COLUMN IF NOT EXISTS password_hash TEXT;")
        
        # BUMP IDS TO 5000+
        cur.execute("SELECT setval(pg_get_serial_sequence('clients', 'id'), GREATEST(MAX(id)+1, 5000), false) FROM clients;")
        
        conn.commit()
        return "<h1>✅ Database Upgraded!</h1><p>Client IDs bumped to 5000+.<br>Password column added.</p><br><a href='/clients'>Back to Clients</a>"
    except Exception as e:
        conn.rollback()
        return f"<h1>Error</h1><p>{e}</p>"
    finally:
        conn.close()