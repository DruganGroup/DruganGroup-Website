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

# --- TAX RATES CONFIGURATION ---
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

# --- HELPER: GET SITE CONFIG ---
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
# 1. NEW QUOTE (With Auto-Pricing & Database Sum)
# =========================================================
@quote_bp.route('/office/quote/new', methods=['GET', 'POST'])
def new_quote():
    if not check_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # --- GET SETTINGS ---
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    country = settings.get('country_code', 'UK')
    vat_reg = settings.get('vat_registered', 'no')
    tax_rate = 0.00
    
    if vat_reg in ['yes', 'on', 'true', '1']:
        manual_rate = settings.get('default_tax_rate')
        if manual_rate and float(manual_rate) > 0:
            tax_rate = float(manual_rate) / 100
        else:
            tax_rate = TAX_RATES.get(country, 0.20)

    # --- HANDLE POST ---
    if request.method == 'POST':
        try:
            client_id = request.form.get('client_id')
            
            # Quick Lead Logic
            if not client_id and request.form.get('new_client_name'):
                cur.execute("""
                    INSERT INTO clients (company_id, name, email, phone, status, billing_address)
                    VALUES (%s, %s, %s, %s, 'Lead', %s)
                    RETURNING id
                """, (comp_id, request.form.get('new_client_name'), request.form.get('new_client_email'), 
                      request.form.get('new_client_phone'), request.form.get('new_client_address')))
                client_id = cur.fetchone()[0]

            if not client_id:
                flash("❌ Error: No Client Selected", "error")
                return redirect(request.url)

            # Generate Reference
            cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,))
            count = cur.fetchone()[0]
            ref = f"Q-{1000 + count + 1}"
            
            # Capture Details
            job_title = request.form.get('job_title')
            job_desc = request.form.get('job_description')
            est_days = request.form.get('estimated_days')
            pref_van = request.form.get('preferred_vehicle_id') or None
            
            # NEW: Capture Property ID
            property_id = request.form.get('property_id') or None

            # Insert Quote Header (Now including property_id)
            cur.execute("""
                INSERT INTO quotes (
                    company_id, client_id, property_id, reference, date, expiry_date, status, total,
                    job_title, job_description, estimated_days, preferred_vehicle_id
                )
                VALUES (%s, %s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days', 'Draft', 0,
                        %s, %s, %s, %s)
                RETURNING id
            """, (comp_id, client_id, property_id, ref, job_title, job_desc, est_days, pref_van))
            
            quote_id = cur.fetchone()[0]

            # --- 1. INSERT AUTO-LABOR LINE ITEM ---
            if pref_van and est_days:
                try:
                    days = float(est_days)
                    cur.execute("SELECT daily_cost, assigned_driver_id, reg_plate FROM vehicles WHERE id = %s", (pref_van,))
                    van = cur.fetchone()
                    
                    if van:
                        van_cost = float(van[0]) if van[0] else 0.0
                        driver_id = van[1]
                        reg_plate = van[2]

                        driver_cost = 0.0
                        if driver_id:
                            cur.execute("SELECT pay_rate FROM staff WHERE id = %s", (driver_id,))
                            d_res = cur.fetchone()
                            if d_res and d_res[0]: driver_cost = float(d_res[0]) * 8 

                        cur.execute("""
                            SELECT SUM(s.pay_rate) FROM vehicle_crew vc
                            JOIN staff s ON vc.staff_id = s.id
                            WHERE vc.vehicle_id = %s
                        """, (pref_van,))
                        c_res = cur.fetchone()
                        crew_hourly_total = float(c_res[0]) if c_res and c_res[0] else 0.0
                        crew_cost = crew_hourly_total * 8

                        daily_rate = van_cost + driver_cost + crew_cost
                        line_total = daily_rate * days

                        if line_total > 0:
                            cur.execute("""
                                INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                                VALUES (%s, %s, %s, %s, %s)
                            """, (quote_id, f"Labor & Logistics: {reg_plate} (Driver + Crew)", days, daily_rate, line_total))
                except Exception as e:
                    print(f"Pricing Engine Error: {e}")

            # --- 2. INSERT MANUAL LINE ITEMS ---
            descriptions = request.form.getlist('desc[]')
            quantities = request.form.getlist('qty[]')
            prices = request.form.getlist('price[]')
            
            for d, q, p in zip(descriptions, quantities, prices):
                if d.strip(): 
                    qty = float(q) if q else 1
                    price = float(p) if p else 0
                    line_net = qty * price
                    
                    cur.execute("""
                        INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (quote_id, d, qty, price, line_net))

            # --- 3. BULLETPROOF TOTAL CALCULATION ---
            # We ask the DB for the sum to ensure Auto + Manual lines are ALL counted
            cur.execute("SELECT SUM(total) FROM quote_items WHERE quote_id = %s", (quote_id,))
            db_sum = cur.fetchone()[0]
            real_net_total = float(db_sum) if db_sum else 0.0
            
            grand_total = real_net_total * (1 + tax_rate)
            
            cur.execute("UPDATE quotes SET total = %s WHERE id = %s", (grand_total, quote_id))
            
            conn.commit()
            flash(f"✅ Quote {ref} Created! Total: £{grand_total:.2f}", "success")
            return redirect(url_for('quote.view_quote', quote_id=quote_id))

        except Exception as e:
            conn.rollback()
            flash(f"Error saving quote: {e}", "error")
            return redirect(request.url)

    # --- GET REQUEST ---
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name ASC", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id = %s AND status = 'Active'", (comp_id,))
    fleet = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]

    pre_client = request.args.get('client_id')
    config = get_site_config(comp_id)
    conn.close()
    
    return render_template('office/create_quote.html', 
                           clients=clients, fleet=fleet, pre_client=pre_client, 
                           brand_color=config['color'], logo_url=config['logo'],
                           settings=settings, tax_rate=tax_rate)
                           
# =========================================================
# 2. VIEW QUOTE (Updated to fetch Title/Desc)
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    if request.args.get('mode') == 'pdf': 
        return redirect(url_for('pdf.download_quote_pdf', quote_id=quote_id)) 

    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    # Updated Query: Added q.job_title [7] and q.job_description [8]
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.date, q.total, q.status, q.expiry_date,
               q.job_title, q.job_description
        FROM quotes q 
        LEFT JOIN clients c ON q.client_id = c.id 
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, comp_id))
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
        
        cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s", (quote_id,))
        
        conn.commit()
        flash(f"✅ Job {job_ref} Created! Materials synced.", "success")
        return redirect(url_for('office.office_calendar'))

    except Exception as e:
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
    
    # 2. Fetch Quote (UPDATED QUERY: Now grabs c.billing_address)
    cur.execute("""
        SELECT q.reference, c.name, c.email, q.job_title, q.job_description, q.date, q.total, c.billing_address
        FROM quotes q JOIN clients c ON q.client_id = c.id
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, company_id))
    q = cur.fetchone()
    
    if not q or not q[2]:
        conn.close(); flash("❌ Client has no email address.", "error")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    # Unpack variables (Added client_addr at the end)
    ref, client_name, client_email, title, desc, q_date, total_val, client_addr = q[0], q[1], q[2], q[3], q[4], q[5], float(q[6] or 0), q[7]

    # 3. Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if 'smtp_host' not in settings:
        conn.close(); flash("⚠️ SMTP Settings missing.", "warning")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # 4. CONFIG & LOGO FIX
    config = get_site_config(company_id)
    
    if config.get('logo') and config['logo'].startswith('/'):
        # Ensure 'import os' and 'current_app' are imported at the top of the file!
        local_path = os.path.join(current_app.root_path, config['logo'].lstrip('/'))
        if os.path.exists(local_path):
            config['logo'] = f"file://{local_path}"

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