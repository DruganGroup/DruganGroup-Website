from flask import Blueprint, render_template, session, redirect, url_for, request, send_file, flash, current_app
from db import get_db, get_site_config
from services.pdf_generator import generate_pdf
from datetime import datetime
import os

pdf_bp = Blueprint('pdf', __name__)

def check_access():
    return 'user_id' in session

# --- HELPER: FORMAT DATE BY COUNTRY ---
def format_date_local(d, country='UK'):
    if not d: return ""
    if isinstance(d, str):
        try: d = datetime.strptime(d, '%Y-%m-%d')
        except: return d
    if country == 'US': return d.strftime('%m/%d/%Y')
    return d.strftime('%d/%m/%Y')

# --- HELPER: CALCULATE TAX ---
def get_tax_rate(settings):
    if settings.get('vat_registered') not in ['yes', 'on', 'true', '1']: return 0.0
    manual_rate = settings.get('default_tax_rate')
    if manual_rate and float(manual_rate) > 0: return float(manual_rate)
    return 20.0 

def get_company_name(cursor, company_id):
    try:
        cursor.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
        res = cursor.fetchone()
        return res[0] if res else "My Company"
    except:
        return "My Company"

def get_smart_terms(settings):
    custom = settings.get('payment_terms')
    if custom and len(custom) > 5: return custom
    days = settings.get('payment_days', '14')
    return f"Payment is due within {days} days of the invoice date."

@pdf_bp.route('/finance/invoice/<int:invoice_id>/download')
def download_invoice_pdf(invoice_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')

    # 1. Fetch Invoice + Linked Data
    cur.execute("""
        SELECT i.id, i.reference, i.date_created, i.due_date, 
               c.name, c.billing_address, c.email, i.total, i.status,
               COALESCE(q.job_title, j.description, 'Invoice') as job_title,
               COALESCE(q.job_description, j.description, '') as job_desc,
               j.property_id, q.property_id
        FROM invoices i 
        JOIN clients c ON i.client_id = c.id
        LEFT JOIN jobs j ON i.job_id = j.id
        LEFT JOIN quotes q ON i.quote_id = q.id
        WHERE i.id = %s AND i.company_id = %s
    """, (invoice_id, comp_id))
    inv = cur.fetchone()
    
    if not inv: conn.close(); return "Invoice not found", 404

    # 2. Resolve Addresses
    # BILLING: Always use the client's billing address
    billing_addr = inv[5]
    
    # SITE: Check Job then Quote for property_id
    site_address_str = ""
    active_prop_id = inv[11] or inv[12]
    
    if active_prop_id:
        cur.execute("SELECT address_line1, postcode FROM properties WHERE id = %s", (active_prop_id,))
        prop = cur.fetchone()
        if prop:
            site_address_str = f"Site: {prop[0]}, {prop[1]}"

    # 3. Inject Site Address into Description
    # This keeps 'Bill To' correct but shows the Site clearly in the body
    job_desc = inv[10]
    if site_address_str:
        job_desc = f"{site_address_str}\n{job_desc}"

    # 4. Fetch Items & Settings
    cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    comp_name = get_company_name(cur, comp_id)
    conn.close()

    # --- THE BULLETPROOF LOGO FIX ---
    config = get_site_config(comp_id)
    if config.get('logo'):
        # 1. Strip all prefixes to get clean filename
        clean_path = config['logo']
        for p in ['/static/', 'static/', '/uploads/', 'uploads/']:
            clean_path = clean_path.replace(p, '')
            
        # 2. Build absolute disk path
        abs_path = os.path.join(current_app.static_folder, 'uploads', clean_path)
        
        # 3. Force 'file://' protocol if file exists
        if os.path.exists(abs_path):
            config['logo'] = f"file://{abs_path}"
    # --------------------------------

    total_val = float(inv[7] or 0)
    user_rate = get_tax_rate(settings)
    divisor = 1 + (user_rate / 100)
    subtotal_val = total_val / divisor
    tax_val = total_val - subtotal_val
    country = settings.get('country_code', 'UK')
    ref_display = inv[1] if inv[1] else "DRAFT"

    context = {
        'invoice': {
            'ref': ref_display, 
            'date': format_date_local(inv[2], country),
            'due': format_date_local(inv[3], country),
            'client_name': inv[4], 
            'client_address': billing_addr, 
            'client_email': inv[6],
            'subtotal': subtotal_val,
            'tax': tax_val,
            'total': total_val,
            'tax_rate_display': user_rate,
            'status': inv[8],
            'currency_symbol': settings.get('currency_symbol', '£'),
            'job_title': inv[9],
            'job_description': job_desc 
        },
        'company': {
            'name': comp_name,
            'address': settings.get('company_address', ''),
            'email': settings.get('company_email', ''),
            'phone': settings.get('company_phone', ''),
            'reg': settings.get('company_reg_number', '')
        },
        'items': items,
        'settings': settings,
        'smart_terms': get_smart_terms(settings),
        'config': config, # This now has the correct file:// path
        'is_quote': False 
    }
    
    filename = f"Invoice_{ref_display}.pdf"
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        return send_file(pdf_path, as_attachment=False, download_name=filename)
    except Exception as e:
        return f"PDF Error: {e}", 500

@pdf_bp.route('/office/quote/<int:quote_id>/download')
def download_quote_pdf(quote_id):
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')

    cur.execute("""
        SELECT q.id, q.reference, q.date, q.expiry_date, 
               c.name, c.billing_address, c.email, q.total, q.status,
               q.job_title, q.job_description, q.property_id
        FROM quotes q 
        JOIN clients c ON q.client_id = c.id 
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, comp_id))
    quote = cur.fetchone()
    
    if not quote: conn.close(); return "Quote not found", 404

    # Resolve Addresses
    billing_addr = quote[5]
    property_id = quote[11]
    
    site_address_str = ""
    if property_id:
        cur.execute("SELECT address_line1, postcode FROM properties WHERE id = %s", (property_id,))
        prop = cur.fetchone()
        if prop:
            site_address_str = f"Site: {prop[0]}, {prop[1]}"

    job_desc = quote[10]
    if site_address_str:
        job_desc = f"{site_address_str}\n{job_desc}"

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    comp_name = get_company_name(cur, comp_id)
    conn.close()

    # --- THE BULLETPROOF LOGO FIX ---
    config = get_site_config(comp_id)
    if config.get('logo'):
        # 1. Strip all prefixes to get clean filename
        clean_path = config['logo']
        for p in ['/static/', 'static/', '/uploads/', 'uploads/']:
            clean_path = clean_path.replace(p, '')
            
        # 2. Build absolute disk path
        abs_path = os.path.join(current_app.static_folder, 'uploads', clean_path)
        
        # 3. Force 'file://' protocol if file exists
        if os.path.exists(abs_path):
            config['logo'] = f"file://{abs_path}"
    # --------------------------------

    total_val = float(quote[7]) if quote[7] else 0
    user_rate = get_tax_rate(settings)
    divisor = 1 + (user_rate / 100)
    subtotal_val = total_val / divisor
    tax_val = total_val - subtotal_val
    country = settings.get('country_code', 'UK')

    context = {
        'invoice': {
            'ref': quote[1], 
            'date': format_date_local(quote[2], country),
            'due': format_date_local(quote[3], country),
            'client_name': quote[4], 
            'client_address': billing_addr, 
            'client_email': quote[6],
            'subtotal': subtotal_val,
            'tax': tax_val,
            'total': total_val,
            'tax_rate_display': user_rate,
            'status': quote[8],
            'currency_symbol': settings.get('currency_symbol', '£'),
            'job_title': quote[9],
            'job_description': job_desc 
        },
        'company': {
            'name': comp_name,
            'address': settings.get('company_address', ''),
            'email': settings.get('company_email', ''),
            'phone': settings.get('company_phone', ''),
            'reg': settings.get('company_reg_number', '')
        },
        'items': items,
        'settings': settings,
        'smart_terms': get_smart_terms(settings),
        'config': config, # Using the fixed config with file://
        'is_quote': True 
    }
    
    filename = f"Quote_{quote[1]}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        return send_file(pdf_path, as_attachment=False, download_name=filename)
    except Exception as e:
        return f"PDF Error: {e}", 500
        
@pdf_bp.route('/office/job/<int:job_id>/material-list')
def download_material_list(job_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Job Details
    cur.execute("SELECT ref, address_line1 FROM jobs JOIN properties ON jobs.property_id = properties.id WHERE jobs.id = %s", (job_id,))
    job = cur.fetchone()
    
    # 2. Fetch Materials (Grouped by Supplier if you track that, or just a list)
    cur.execute("SELECT description, quantity FROM job_materials WHERE job_id = %s", (job_id,))
    items = [{'desc': r[0], 'qty': r[1]} for r in cur.fetchall()]
    
    conn.close()
    
    # 3. Generate PDF
    context = {
        'ref': job[0],
        'address': job[1],
        'items': items,
        'config': get_site_config(session.get('company_id'))
    }
    
    return generate_pdf('finance/pdf_materials.html', context, f"Materials_{job[0]}.pdf")
    
@pdf_bp.route('/office/job/<int:job_id>/rams/create')
def create_rams_form(job_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. Fetch Job Info
    cur.execute("""
        SELECT j.ref, j.description, c.name, p.address_line1 
        FROM jobs j
        JOIN clients c ON j.client_id = c.id
        JOIN properties p ON j.property_id = p.id
        WHERE j.id = %s
    """, (job_id,))
    job = cur.fetchone()
    conn.close()

    if not job: return "Job not found", 404

    # 2. "Smart" Hazard Detection (Auto-ticks boxes for you)
    desc_lower = job[1].lower()
    hazards = []
    
    # Basic logic to save you typing
    if 'roof' in desc_lower or 'gutter' in desc_lower: hazards.append('Working at Height')
    if 'electr' in desc_lower or 'light' in desc_lower: hazards.append('Electricity')
    if 'garden' in desc_lower or 'dig' in desc_lower: hazards.append('Manual Handling')
    if 'paint' in desc_lower: hazards.append('Dust & Fumes')
    
    # Default PPE
    ppe = ['Safety Boots', 'Hi-Vis Vest']

    # 3. Default Method Statement (Generic template)
    method_template = (
        "1. Arrive on site and report to client.\n"
        "2. Assess work area for immediate hazards.\n"
        "3. Don appropriate PPE.\n"
        "4. Carry out works: " + job[1] + ".\n"
        "5. Clear away waste and tools.\n"
        "6. Final inspection and sign-off."
    )

    data = {
        'job_id': job_id,
        'ref': job[0],
        'client': job[2],
        'address': job[3],
        'hazards': hazards,
        'ppe': ppe,
        'method': method_template
    }

    return render_template('office/create_rams.html', data=data)


# --- ROUTE 2: SAVE & GENERATE THE PDF ---
@pdf_bp.route('/office/job/<int:job_id>/rams/save', methods=['POST'])
def save_and_download_rams(job_id):
    if not check_access(): return redirect(url_for('auth.login'))

    # 1. Get Data from Form
    ref = request.form.get('ref')
    client = request.form.get('client')
    address = request.form.get('address')
    method = request.form.get('method_statement')
    
    # Get checkboxes (returns a list)
    hazards = request.form.getlist('hazards')
    ppe = request.form.getlist('ppe')

    # 2. Prepare Context for PDF
    context = {
        'ref': ref,
        'date': datetime.now().strftime('%d/%m/%Y'),
        'client_name': client,
        'site_address': address,
        'description': method, # Using the method statement as the main body
        'risks': hazards,
        'ppe': ppe,
        'config': get_site_config(session.get('company_id'))
    }

    # 3. Generate PDF (Uses the template we made earlier)
    return generate_pdf('finance/pdf_rams.html', context, f"RAMS_{ref}.pdf")