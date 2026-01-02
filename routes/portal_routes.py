from flask import Blueprint, render_template, session, redirect, url_for, flash, request, send_file, abort
from db import get_db, get_site_config
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import os

portal_bp = Blueprint('portal', __name__)

# --- HELPERS ---
def check_portal_access():
    if 'portal_client_id' not in session: return False
    return True

def get_redirect_target():
    # Helper to find the correct login page even if session is weird
    comp_id = session.get('portal_company_id')
    if comp_id:
        return url_for('portal.portal_login', company_id=comp_id)
    return '/' # Fallback if totally lost

# --- 1. PORTAL LOGIN ---
@portal_bp.route('/portal/login/<int:company_id>', methods=['GET', 'POST'])
def portal_login(company_id):
    config = get_site_config(company_id)
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT id, name, password_hash FROM clients WHERE email = %s AND company_id = %s", (email, company_id))
        client = cur.fetchone()
        conn.close()
        
        if client and client[2] and check_password_hash(client[2], password):
            session['portal_client_id'] = client[0]
            session['portal_client_name'] = client[1]
            session['portal_company_id'] = company_id
            return redirect(url_for('portal.portal_home'))
        else:
            flash("Invalid email or password", "error")
            
    return render_template('portal/portal_login.html', 
                         company_name=config.get('name'), 
                         logo_url=config.get('logo'), 
                         brand_color=config.get('color'))

# --- 2. DASHBOARD ---
@portal_bp.route('/portal/home')
def portal_home():
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Properties (With new columns)
    # Using '0' for missing phone/key codes to prevent crashes if columns are empty
    try:
        cur.execute("""
            SELECT id, address_line1, postcode, type, tenant_name, tenant_phone, key_code 
            FROM properties WHERE client_id = %s
        """, (client_id,))
        properties = cur.fetchall()
    except:
        # Fallback if upgrade script wasn't run yet
        cur.execute("SELECT id, address_line1, postcode, type, tenant_name FROM properties WHERE client_id = %s", (client_id,))
        properties = [r + (None, None) for r in cur.fetchall()]

    # 2. Fetch Recent Invoices
    cur.execute("SELECT id, invoice_number, date_issue, total_amount, status FROM invoices WHERE client_id = %s ORDER BY date_issue DESC LIMIT 3", (client_id,))
    recent_invoices = cur.fetchall()
    
    # 3. Fetch Recent Quotes
    try:
        cur.execute("SELECT id, reference, total, status FROM quotes WHERE client_id = %s ORDER BY date DESC LIMIT 3", (client_id,))
        recent_quotes = cur.fetchall()
    except:
        recent_quotes = []

    conn.close()
    
    return render_template('portal/portal_home.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         properties=properties,
                         recent_invoices=recent_invoices,
                         recent_quotes=recent_quotes)

# --- 3. LOGOUT ---
@portal_bp.route('/portal/logout')
def portal_logout():
    comp_id = session.get('portal_company_id')
    session.clear()
    if comp_id:
        return redirect(url_for('portal.portal_login', company_id=comp_id))
    return "Logged out"

# --- 4. MY INVOICES ---
@portal_bp.route('/portal/invoices')
def portal_invoices():
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, invoice_number, date_issue, total_amount, status, file_path FROM invoices WHERE client_id = %s ORDER BY date_issue DESC", (client_id,))
    invoices = cur.fetchall()
    conn.close()
    
    return render_template('portal/portal_invoices.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         invoices=invoices)

# --- 5. MY PROFILE (View & Update) ---
@portal_bp.route('/portal/profile', methods=['GET', 'POST'])
def portal_profile():
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    if request.method == 'POST':
        new_name = request.form.get('name')
        new_email = request.form.get('email')
        new_password = request.form.get('password')
        
        try:
            cur.execute("UPDATE clients SET name = %s, email = %s WHERE id = %s", (new_name, new_email, client_id))
            if new_password:
                hashed = generate_password_hash(new_password)
                cur.execute("UPDATE clients SET password_hash = %s WHERE id = %s", (hashed, client_id))
                
            conn.commit()
            flash("✅ Profile updated successfully!", "success")
            session['portal_client_name'] = new_name 
        except Exception as e:
            conn.rollback()
            flash(f"Error updating profile: {e}", "error")

    cur.execute("SELECT name, email FROM clients WHERE id = %s", (client_id,))
    client = cur.fetchone()
    conn.close()
    
    return render_template('portal/portal_profile.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         client=client)

# --- 6. ADD PROPERTY (Action) ---
@portal_bp.route('/portal/property/add', methods=['POST'])
def add_property():
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    
    address = request.form.get('address')
    postcode = request.form.get('postcode')
    p_type = request.form.get('type')
    tenant_name = request.form.get('tenant_name')
    tenant_phone = request.form.get('tenant_phone')
    key_code = request.form.get('key_code')

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO properties (company_id, client_id, address_line1, postcode, type, tenant_name, tenant_phone, key_code)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, client_id, address, postcode, p_type, tenant_name, tenant_phone, key_code))
        conn.commit()
        flash("✅ New property added to your list.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error adding property: {e}", "error")
    finally:
        conn.close()

    return redirect('/portal/home')

# --- 7. PROPERTY DETAIL VIEW ---
@portal_bp.route('/portal/property/<int:property_id>')
def property_detail(property_id):
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Property (Robust check for new columns)
    try:
        cur.execute("""
            SELECT id, address_line1, postcode, type, tenant_name, tenant_phone, key_code 
            FROM properties WHERE id = %s AND client_id = %s
        """, (property_id, client_id))
    except:
        cur.execute("""
            SELECT id, address_line1, postcode, type, tenant_name, NULL, NULL 
            FROM properties WHERE id = %s AND client_id = %s
        """, (property_id, client_id))
        
    prop = cur.fetchone()
    
    if not prop:
        conn.close()
        flash("Property not found or access denied.", "error")
        return redirect('/portal/home')

    # Fetch Job History for this property
    # Check if 'property_id' exists in jobs table first (via try/except query)
    try:
        cur.execute("""
            SELECT id, ref, status, description, created_at 
            FROM jobs WHERE property_id = %s ORDER BY created_at DESC
        """, (property_id,))
        job_history = cur.fetchall()
    except:
        job_history = [] # Jobs table might not be linked yet

    conn.close()
    
    # Pass 'properties' list for the modal dropdown in case they want to log a ticket from this page
    # (Re-fetching just the list for the modal)
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id, address_line1, postcode, type FROM properties WHERE client_id = %s", (client_id,))
    properties_list = cur.fetchall()
    conn.close()
    
    return render_template('portal/portal_property_view.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         prop=prop,
                         job_history=job_history,
                         properties=properties_list)

# --- 8. SUBMIT SERVICE REQUEST ---
@portal_bp.route('/portal/request/submit', methods=['POST'])
def submit_request():
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    
    property_id = request.form.get('property_id')
    description = request.form.get('description')
    severity = request.form.get('severity', 'Low')
    
    image_url = None
    file = request.files.get('image')
    if file and file.filename != '':
        filename = secure_filename(f"req_{client_id}_{file.filename}")
        upload_path = os.path.join('static/uploads/requests', filename)
        os.makedirs('static/uploads/requests', exist_ok=True)
        file.save(upload_path)
        image_url = f"/static/uploads/requests/{filename}"

    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO service_requests (client_id, property_id, issue_description, severity, image_url, status)
            VALUES (%s, %s, %s, %s, %s, 'Open')
        """, (client_id, property_id, description, severity, image_url))
        conn.commit()
        flash("✅ Maintenance request submitted. We will contact you shortly.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()

    return redirect('/portal/home')

# --- 9. MY QUOTES PAGE ---
@portal_bp.route('/portal/quotes')
def portal_quotes():
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    comp_id = session['portal_company_id']
    config = get_site_config(comp_id)
    
    conn = get_db(); cur = conn.cursor()
    
    try:
        cur.execute("SELECT id, reference, date, total, status FROM quotes WHERE client_id = %s ORDER BY date DESC", (client_id,))
        quotes = cur.fetchall()
    except:
        quotes = []
        
    conn.close()
    
    return render_template('portal/portal_quotes.html',
                         client_name=session['portal_client_name'],
                         company_name=config.get('name'),
                         logo_url=config.get('logo'),
                         brand_color=config.get('color'),
                         quotes=quotes)

# --- 10. QUOTE DETAIL & ACTIONS ---
@portal_bp.route('/portal/quote/<int:quote_id>')
def quote_detail(quote_id):
    if not check_portal_access(): return redirect(get_redirect_target())
    
    client_id = session['portal_client_id']
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("SELECT id, reference, date, total, status FROM quotes WHERE id = %s AND client_id = %s", (quote_id, client_id))
    quote = cur.fetchone()
    
    if not quote:
        conn.close()
        return "Quote not found", 404

    items = []
    try:
        cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
        items = cur.fetchall()
    except:
        pass 

    config = get_site_config(session['portal_company_id'])
    conn.close()
    
    return render_template('portal/portal_quote_view.html',
                         company_name=config.get('name'),
                         brand_color=config.get('color'),
                         quote=quote,
                         items=items)

@portal_bp.route('/portal/quote/<int:quote_id>/accept')
def quote_accept(quote_id):
    if not check_portal_access(): return redirect(get_redirect_target())
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s AND client_id = %s", (quote_id, session['portal_client_id']))
    conn.commit(); conn.close()
    flash("✅ Quote Accepted! We will be in touch.", "success")
    return redirect(url_for('portal.portal_quotes'))

@portal_bp.route('/portal/quote/<int:quote_id>/decline')
def quote_decline(quote_id):
    if not check_portal_access(): return redirect(get_redirect_target())
    conn = get_db(); cur = conn.cursor()
    cur.execute("UPDATE quotes SET status = 'Declined' WHERE id = %s AND client_id = %s", (quote_id, session['portal_client_id']))
    conn.commit(); conn.close()
    flash("❌ Quote Declined.", "warning")
    return redirect(url_for('portal.portal_quotes'))

# --- 11. FILE DOWNLOAD (Handling Invoices) ---
@portal_bp.route('/portal/download/<path:filename>')
def download_file(filename):
    if not check_portal_access(): return redirect(get_redirect_target())
    
    # Security: Ensure they can only download their own company files
    # Note: In production, verify the file belongs to the user in DB
    safe_path = os.path.join('static', filename)
    if os.path.exists(safe_path):
        return send_file(safe_path, as_attachment=True)
    else:
        return "File not found", 404