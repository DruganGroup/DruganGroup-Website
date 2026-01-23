from flask import Blueprint, render_template, session, redirect, url_for, flash, request, current_app
from db import get_db
from datetime import datetime
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from services.pdf_generator import generate_pdf

quote_bp = Blueprint('quote', __name__)

# --- TAX RATES CONFIGURATION (PRESERVED) ---
TAX_RATES = {
    'UK': 0.20,  # United Kingdom (20%)
    'IE': 0.23,  # Ireland (23%)
    'US': 0.00,  # USA (Sales tax varies)
    'CAN': 0.05, # Canada (GST 5%)
    'AUS': 0.10, # Australia (GST 10%)
    'NZ': 0.15,  # New Zealand (GST 15%)
    'FR': 0.20,  # France
    'DE': 0.19,  # Germany
    'ES': 0.21   # Spain
}

def check_access():
    if 'user_id' not in session: return False
    return True

# --- HELPER: GET SITE CONFIG (PRESERVED) ---
def get_site_config(comp_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()
    return {
        'color': settings.get('brand_color', '#333333'),
        'logo': settings.get('logo', '')
    }

# =========================================================
# 1. NEW QUOTE (Display Page) - UPGRADED
# =========================================================
@quote_bp.route('/office/quote/new', methods=['GET'])
def new_quote():
    if not check_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # 1. Fetch Clients
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s AND status='Active' ORDER BY name", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

    # 2. Fetch Materials
    cur.execute("SELECT id, name, cost_price FROM materials WHERE company_id=%s ORDER BY name", (comp_id,))
    materials = [{'id': r[0], 'name': r[1], 'price': r[2]} for r in cur.fetchall()]

    # 3. FETCH VEHICLES & CALCULATE "TRUE GANG COST" (Matches Finance Logic)
    # This fixes the dropdown showing £0 or incorrect prices
    cur.execute("""
        SELECT v.id, v.reg_plate, v.make_model, v.daily_cost, v.assigned_driver_id
        FROM vehicles v
        WHERE v.company_id = %s AND v.status = 'Active'
    """, (comp_id,))
    
    vehicles = []
    for r in cur.fetchall():
        v_id, reg, model, base_cost, driver_id = r
        daily_total = float(base_cost or 0)
        
        # A. Add Driver Cost (Checking Pay Model)
        if driver_id:
            cur.execute("SELECT pay_rate, pay_model FROM staff WHERE id = %s", (driver_id,))
            d_row = cur.fetchone()
            if d_row:
                rate, model_type = float(d_row[0] or 0), d_row[1]
                if model_type == 'Hour': daily_total += (rate * 8)
                elif model_type == 'Day': daily_total += rate
                elif model_type == 'Year': daily_total += (rate / 260)

        # B. Add Crew Cost (Checking Pay Model)
        cur.execute("""
            SELECT s.pay_rate, s.pay_model FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (v_id,))
        for c_row in cur.fetchall():
            rate, model_type = float(c_row[0] or 0), c_row[1]
            if model_type == 'Hour': daily_total += (rate * 8)
            elif model_type == 'Day': daily_total += rate
            elif model_type == 'Year': daily_total += (rate / 260)

        vehicles.append({
            'id': v_id, 
            'reg_plate': reg, 
            'make_model': model, 
            'daily_cost': daily_total
        })

    # 4. Fetch Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    conn.close()

    # Tax Logic (PRESERVED)
    country = settings.get('country_code', 'UK')
    vat_reg = settings.get('vat_registered', 'no')
    tax_rate = 0.00
    
    if vat_reg in ['yes', 'on', 'true', '1']:
        manual_rate = settings.get('default_tax_rate')
        if manual_rate and float(manual_rate) > 0:
            tax_rate = float(manual_rate) / 100
        else:
            tax_rate = TAX_RATES.get(country, 0.20)

    # 5. Lookup Service Request (Preserved)
    request_id = request.args.get('request_id')
    source_request = None
    # (Logic for source_request was in office_routes, adding simplest version here if needed, 
    # otherwise defaults to None to avoid errors)
    
    return render_template('office/create_quote.html', 
                           clients=clients, 
                           materials=materials, 
                           vehicles=vehicles, # Passed correctly as 'vehicles'
                           settings=settings, 
                           tax_rate=tax_rate,
                           pre_client=request.args.get('client_id'),
                           source_request=source_request)

# =========================================================
# 2. SAVE UNIFIED QUOTE (POST Logic) - NEW & UPGRADED
# =========================================================
@quote_bp.route('/office/quote/save-unified', methods=['POST'])
def save_unified_quote():
    if not check_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    try:
        # 1. Quick Lead Logic
        client_id = request.form.get('client_id')
        if not client_id and request.form.get('new_client_name'):
            cur.execute("""
                INSERT INTO clients (company_id, name, email, phone, status, billing_address)
                VALUES (%s, %s, %s, %s, 'Lead', %s) RETURNING id
            """, (comp_id, request.form.get('new_client_name'), request.form.get('new_client_email'), 
                  request.form.get('new_client_phone'), request.form.get('new_client_address')))
            client_id = cur.fetchone()[0]

        if not client_id:
            flash("❌ Error: No Client Selected", "error")
            return redirect(request.referrer)

        # 2. Generate Ref
        cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,))
        count = cur.fetchone()[0]
        ref = f"Q-{1000 + count + 1}"

        # 3. Capture Details
        job_title = request.form.get('job_title')
        job_desc = request.form.get('job_description')
        est_days = float(request.form.get('estimated_days') or 1)
        pref_van = request.form.get('preferred_vehicle_id') or None
        prop_id = request.form.get('property_id') or None

        # 4. Insert Header
        cur.execute("""
            INSERT INTO quotes (
                company_id, client_id, property_id, reference, date, expiry_date, status, total,
                job_title, job_description, estimated_days, preferred_vehicle_id
            )
            VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days', 'Draft', 0,
                    %s, %s, %s, %s)
            RETURNING id
        """, (comp_id, client_id, prop_id, ref, job_title, job_desc, est_days, pref_van))
        quote_id = cur.fetchone()[0]

        # 5. INSERT AUTO-LABOR (The UPGRADED Smart Logic)
        if pref_van:
            cur.execute("SELECT daily_cost, assigned_driver_id, reg_plate FROM vehicles WHERE id = %s", (pref_van,))
            van = cur.fetchone()
            
            if van:
                daily_total = float(van[0]) if van[0] else 0.0
                driver_id = van[1]
                reg_plate = van[2]

                # Add Driver (Checking Pay Model)
                if driver_id:
                    cur.execute("SELECT pay_rate, pay_model FROM staff WHERE id=%s", (driver_id,))
                    d_row = cur.fetchone()
                    if d_row:
                        rate, model = float(d_row[0] or 0), d_row[1]
                        if model == 'Hour': daily_total += (rate * 8)
                        elif model == 'Day': daily_total += rate
                        elif model == 'Year': daily_total += (rate / 260)

                # Add Crew (Checking Pay Model)
                cur.execute("""
                    SELECT s.pay_rate, s.pay_model FROM vehicle_crews vc
                    JOIN staff s ON vc.staff_id = s.id
                    WHERE vc.vehicle_id = %s
                """, (pref_van,))
                for c_row in cur.fetchall():
                    rate, model = float(c_row[0] or 0), c_row[1]
                    if model == 'Hour': daily_total += (rate * 8)
                    elif model == 'Day': daily_total += rate
                    elif model == 'Year': daily_total += (rate / 260)

                res_total = daily_total * est_days
                if res_total > 0:
                    cur.execute("""
                        INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (quote_id, f"Resources: {reg_plate} (Driver + Crew)", est_days, daily_total, res_total))

        # 6. Save Manual Items
        descriptions = request.form.getlist('desc[]')
        quantities = request.form.getlist('qty[]')
        prices = request.form.getlist('price[]')
        
        for d, q, p in zip(descriptions, quantities, prices):
            if d.strip(): 
                qty = float(q) if q else 1
                price = float(p) if p else 0
                cur.execute("""
                    INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                    VALUES (%s, %s, %s, %s, %s)
                """, (quote_id, d, qty, price, (qty * price)))

        # 7. Update Grand Total (Ask DB for sum)
        cur.execute("SELECT SUM(total) FROM quote_items WHERE quote_id = %s", (quote_id,))
        db_sum = cur.fetchone()[0]
        net = float(db_sum) if db_sum else 0.0
        
        # Calculate tax again for saving total
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        country = settings.get('country_code', 'UK')
        vat_reg = settings.get('vat_registered', 'no')
        tax_rate = 0.0
        if vat_reg in ['yes', 'on', 'true', '1']:
            manual = settings.get('default_tax_rate')
            tax_rate = float(manual)/100 if manual else TAX_RATES.get(country, 0.20)
            
        grand_total = net * (1 + tax_rate)
        cur.execute("UPDATE quotes SET total = %s WHERE id = %s", (grand_total, quote_id))
        
        conn.commit()
        flash(f"✅ Quote {ref} Created! Total: {settings.get('currency_symbol', '£')}{grand_total:.2f}", "success")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    except Exception as e:
        conn.rollback()
        flash(f"Error saving quote: {e}", "error")
        return redirect(request.referrer)
    finally:
        conn.close()

@quote_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    if request.args.get('mode') == 'pdf': 
        return redirect(url_for('pdf.download_quote_pdf', quote_id=quote_id)) 

    comp_id = session.get('company_id')
    
    config = get_site_config(comp_id)

    if config.get('logo') and not config['logo'].startswith('/uploads/'):
        if config['logo'].startswith('uploads/'):
            config['logo'] = '/' + config['logo']
        else:
            config['logo'] = f"/uploads/company_{comp_id}/logos/{config['logo']}"

    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""        SELECT q.id, c.name, q.reference, q.date, q.total, q.status, q.expiry_date,
               q.job_title, q.job_description
        FROM quotes q 
        LEFT JOIN clients c ON q.client_id = c.id 
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, comp_id))
    # --- INDENTATION FIX END ---
    
    quote = cur.fetchone()

    cur.execute("SELECT value FROM settings WHERE key = 'currency_symbol' AND company_id = %s", (comp_id,))
    res = cur.fetchone()
    currency = res[0] if res else '£'

    conn.close()
    
    if not quote: return "Quote not found", 404
    
    return render_template('office/view_quote_dashboard.html', 
                           quote=quote, 
                           currency_symbol=currency,
                           brand_color=config['color'], 
                           logo_url=config['logo'])
                           
@quote_bp.route('/office/quote/<int:quote_id>/book-job')
def convert_to_job(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')

    try:
        # 1. Fetch Quote Details (Now fetching property_id)
        cur.execute("""
            SELECT client_id, property_id, reference, total, job_title, job_description, estimated_days, preferred_vehicle_id
            FROM quotes WHERE id = %s AND company_id = %s
        """, (quote_id, comp_id))
        quote = cur.fetchone()
        
        if not quote: return "Quote not found", 404
        
        client_id, prop_id, q_ref, total, title, q_desc, days, van_id = quote

        # 2. Determine Description
        desc = ""
        if title:
            desc = f"{title} - {q_desc}" if q_desc else title
        else:
            cur.execute("SELECT description FROM quote_items WHERE quote_id = %s LIMIT 1", (quote_id,))
            item = cur.fetchone()
            desc = item[0] if item else f"Work from Quote {q_ref}"

        job_ref = q_ref.replace('Q-', 'JOB-')
        
        # --- TRANSACTION START ---
        
        # 3. INSERT JOB (Uses prop_id from the Quote)
        cur.execute("""
            INSERT INTO jobs (company_id, client_id, property_id, ref, description, status, quote_id, quote_total, vehicle_id, estimated_days)
            VALUES (%s, %s, %s, %s, %s, 'Accepted', %s, %s, %s, %s)
            RETURNING id
        """, (comp_id, client_id, prop_id, job_ref, desc, quote_id, total, van_id, days))
        job_id = cur.fetchone()[0]

        # 4. COPY MATERIALS (THE FIX: Sync Quote Items to Job Materials)
        cur.execute("""
            INSERT INTO job_materials (job_id, description, quantity, unit_price)
            SELECT %s, description, quantity, unit_price 
            FROM quote_items WHERE quote_id = %s
        """, (job_id, quote_id))
        
        # 5. UPDATE QUOTE STATUS
        cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s", (quote_id,))
        
        # --- TRANSACTION COMMIT ---
        conn.commit()
        flash(f"✅ Job {job_ref} Created! Materials synced.", "success")
        return redirect(url_for('office.office_calendar'))

    except Exception as e:
        # --- ROLLBACK ON ERROR ---
        conn.rollback()
        flash(f"Error converting to job: {e}", "error")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))
    finally:
        conn.close()

@quote_bp.route('/office/quote/<int:quote_id>/email')
def email_quote(quote_id):
    # 1. Security Check
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 2. Fetch Quote
    cur.execute("""
        SELECT q.reference, c.name, c.email, q.job_title, q.job_description, q.date, q.total, c.billing_address
        FROM quotes q JOIN clients c ON q.client_id = c.id
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, company_id))
    q = cur.fetchone()
    
    if not q or not q[2]:
        conn.close(); flash("❌ Client has no email address.", "error")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    # Unpack variables
    ref, client_name, client_email, title, desc, q_date, total_val, client_addr = q[0], q[1], q[2], q[3], q[4], q[5], float(q[6] or 0), q[7]

    # 3. Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if 'smtp_host' not in settings:
        conn.close(); flash("⚠️ SMTP Settings missing.", "warning")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # 4. CONFIG & LOGO FIX (Use Disk Path for PDF Engine)
    config = get_site_config(company_id)
    
    # (This block MUST be indented inside the function)
    if config.get('logo'):
        # Convert web path to the actual disk path
        clean_path = config['logo'].replace('/uploads/', '').replace('uploads/', '').replace('/static/', '').replace('static/', '')
        local_path = os.path.join(current_app.static_folder, 'uploads', clean_path)
        
        if os.path.exists(local_path):
            config['logo'] = local_path

    # 5. Date & Context
    country = settings.get('country_code', 'UK')
    date_fmt = '%m/%d/%Y' if country == 'US' else '%d/%m/%Y'
    formatted_date = q_date.strftime(date_fmt) if q_date else datetime.now().strftime(date_fmt)

    context = {
        'invoice': {
            'ref': ref, 
            'date': formatted_date,
            'job_title': title,          
            'job_description': desc,
            'total': total_val,
            'subtotal': total_val, 
            'tax': 0.0,
            'client_name': client_name,
            'client_address': client_addr,
            'client_email': client_email,
            'currency_symbol': settings.get('currency_symbol', '£')
        }, 
        'items': items, 
        'settings': settings, 
        'config': config, 
        'is_quote': True
    }

    filename = f"Quote_{ref}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        # 6. Send Email
        msg = MIMEMultipart()
        msg['From'] = settings.get('smtp_email')
        msg['To'] = client_email
        msg['Subject'] = f"Quote {ref} - {title or 'Proposal'}"
        
        body = f"Dear {client_name},\n\nPlease find attached the quote for {title}.\n\nTotal: {settings.get('currency_symbol','£')}{total_val:.2f}\n\nKind regards,\n{session.get('company_name')}"
        msg.attach(MIMEText(body, 'plain'))
        
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        server = smtplib.SMTP(settings['smtp_host'], int(settings.get('smtp_port', 587)))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        
        cur.execute("UPDATE quotes SET status = 'Sent' WHERE id = %s", (quote_id,))
        conn.commit()
        flash(f"✅ Quote emailed to {client_email}!", "success")

    except Exception as e:
        flash(f"❌ Email failed: {e}", "error")
    
    conn.close()
    return redirect(url_for('quote.view_quote', quote_id=quote_id))
    
    if config.get('logo'):
    # Convert web path to the actual disk path
    clean_path = config['logo'].replace('/uploads/', '').replace('uploads/', '').replace('/static/', '').replace('static/', '')
    local_path = os.path.join(current_app.static_folder, 'uploads', clean_path)

    if os.path.exists(local_path):
        config['logo'] = local_path

    # 5. Date & Context
    country = settings.get('country_code', 'UK')
    date_fmt = '%m/%d/%Y' if country == 'US' else '%d/%m/%Y'
    formatted_date = q_date.strftime(date_fmt) if q_date else datetime.now().strftime(date_fmt)

    context = {
        'invoice': {
            'ref': ref, 
            'date': formatted_date,
            'job_title': title,          
            'job_description': desc,
            'total': total_val,
            'subtotal': total_val, 
            'tax': 0.0,
            
            # --- THE FIX FOR "NONE" ---
            'client_name': client_name,      # Passed to PDF
            'client_address': client_addr,   # Passed to PDF
            'client_email': client_email,    # Passed to PDF
            # --------------------------

            'currency_symbol': settings.get('currency_symbol', '£')
        }, 
        'items': items, 
        'settings': settings, 
        'config': config, 
        'is_quote': True
    }

    filename = f"Quote_{ref}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        # 6. Send Email
        msg = MIMEMultipart()
        msg['From'] = settings.get('smtp_email')
        msg['To'] = client_email
        msg['Subject'] = f"Quote {ref} - {title or 'Proposal'}"
        
        body = f"Dear {client_name},\n\nPlease find attached the quote for {title}.\n\nTotal: {settings.get('currency_symbol','£')}{total_val:.2f}\n\nKind regards,\n{session.get('company_name')}"
        msg.attach(MIMEText(body, 'plain'))
        
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

        server = smtplib.SMTP(settings['smtp_host'], int(settings.get('smtp_port', 587)))
        server.starttls()
        server.login(settings['smtp_email'], settings['smtp_password'])
        server.send_message(msg)
        server.quit()
        
        cur.execute("UPDATE quotes SET status = 'Sent' WHERE id = %s", (quote_id,))
        conn.commit()
        flash(f"✅ Quote emailed to {client_email}!", "success")

    except Exception as e:
        flash(f"❌ Email failed: {e}", "error")
    
    conn.close()
    return redirect(url_for('quote.view_quote', quote_id=quote_id))
  
@quote_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    conn = get_db(); cur = conn.cursor(); comp_id = session.get('company_id')

    # 1. Fetch Quote Data
    cur.execute("SELECT client_id, total, status, reference FROM quotes WHERE id = %s AND company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    if not quote: return "Quote not found", 404
    if quote[2] == 'Converted': return redirect(url_for('quote.view_quote', quote_id=quote_id))

    # 2. Find Linked Job
    cur.execute("SELECT id FROM jobs WHERE quote_id = %s", (quote_id,))
    job_row = cur.fetchone(); job_id = job_row[0] if job_row else None

    # 3. Get Payment Days (RESTORED)
    cur.execute("SELECT value FROM settings WHERE key = 'payment_days' AND company_id = %s", (comp_id,))
    res = cur.fetchone(); days = int(res[0]) if res and res[0] else 14 

    # 4. Create Invoice (UPDATED: Writes to reference, date, total)
    new_ref = f"INV-{quote[3]}" 
    try:
        cur.execute(f"""
            INSERT INTO invoices (company_id, client_id, job_id, quote_id, reference, date, due_date, status, total)
            VALUES (%s, %s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '{days} days', 'Unpaid', %s)
            RETURNING id
        """, (comp_id, quote[0], job_id, quote_id, new_ref, quote[1]))
        
        new_inv_id = cur.fetchone()[0]

        cur.execute("INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total) SELECT %s, description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (new_inv_id, quote_id))
        cur.execute("UPDATE quotes SET status = 'Converted' WHERE id = %s", (quote_id,))
        conn.commit()
        flash(f"✅ Converted to Invoice {new_ref}", "success")
        return redirect(f"/office/job/{job_id}/files") if job_id else redirect(url_for('finance.finance_invoices'))
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error"); return redirect(url_for('quote.view_quote', quote_id=quote_id))
    finally: conn.close()
    
# =========================================================
# 6. PDF REDIRECT
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>/pdf')
def pdf_redirect(quote_id):
    # This catches the old link and sends it to the new PDF engine
    return redirect(url_for('pdf.download_quote_pdf', quote_id=quote_id))