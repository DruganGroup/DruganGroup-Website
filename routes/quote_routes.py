from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from db import get_db, get_site_config
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from services.pdf_generator import generate_pdf

quote_bp = Blueprint('quote', __name__)

# --- TAX RATES CONFIGURATION ---
# Matches the values in your Settings > General page
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

# =========================================================
# 1. THE SMART QUOTE BUILDER
# =========================================================
@quote_bp.route('/office/quote/new', methods=['GET', 'POST'])
def new_quote():
    if not check_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()

    # --- 1. GET SETTINGS (CRITICAL FIX) ---
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    # DETERMINE TAX RATE
    country = settings.get('country_code', 'UK')
    vat_reg = settings.get('vat_registered', 'no')
    
    # Default to 0.00
    tax_rate = 0.00
    
    # Only apply tax if they have ticked "VAT Registered" in settings
    if vat_reg in ['yes', 'on', 'true', '1']:
        # CHECK DATABASE FIRST (Manual Override)
        manual_rate = settings.get('default_tax_rate')
        
        if manual_rate and float(manual_rate) > 0:
            tax_rate = float(manual_rate) / 100  # Convert 20 to 0.20
        else:
            # FALLBACK TO AUTO-DETECT (Hardcoded List)
            tax_rate = TAX_RATES.get(country, 0.20)

    # HANDLE POST (Save Quote)
    if request.method == 'POST':
        try:
            client_id = request.form.get('client_id')
            
            # Handle "Quick Lead" Creation
            if not client_id and request.form.get('new_client_name'):
                cur.execute("""
                    INSERT INTO clients (company_id, name, email, phone, status, billing_address)
                    VALUES (%s, %s, %s, %s, 'Lead', %s)
                    RETURNING id
                """, (
                    comp_id, 
                    request.form.get('new_client_name'), 
                    request.form.get('new_client_email'), 
                    request.form.get('new_client_phone'),
                    request.form.get('new_client_address')
                ))
                client_id = cur.fetchone()[0]

            if not client_id:
                flash("❌ Error: No Client Selected or Created", "error")
                return redirect(request.url)

            # Create Header
            cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id = %s", (comp_id,))
            count = cur.fetchone()[0]
            ref = f"Q-{1000 + count + 1}"
            
            cur.execute("""
                INSERT INTO quotes (company_id, client_id, reference, date, expiry_date, status, total)
                VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '30 days', 'Draft', 0)
                RETURNING id
            """, (comp_id, client_id, ref))
            quote_id = cur.fetchone()[0]
            
            # Save Items
            descriptions = request.form.getlist('desc[]')
            quantities = request.form.getlist('qty[]')
            prices = request.form.getlist('price[]')
            
            total_net = 0.0
            
            for d, q, p in zip(descriptions, quantities, prices):
                if d.strip(): 
                    qty = float(q) if q else 1
                    price = float(p) if p else 0
                    line_net = qty * price
                    total_net += line_net
                    
                    cur.execute("""
                        INSERT INTO quote_items (quote_id, description, quantity, unit_price, total)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (quote_id, d, qty, price, line_net))

            # Update Grand Total (Net + Tax)
            grand_total = total_net * (1 + tax_rate)
            cur.execute("UPDATE quotes SET total = %s WHERE id = %s", (grand_total, quote_id))
            
            conn.commit()
            flash(f"✅ Quote {ref} Created!", "success")
            return redirect(url_for('quote.view_quote', quote_id=quote_id))

        except Exception as e:
            conn.rollback()
            flash(f"Error saving quote: {e}", "error")
            return redirect(request.url)

    # --- GET REQUEST ---
    cur.execute("SELECT id, name FROM clients WHERE company_id = %s ORDER BY name ASC", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    pre_client = request.args.get('client_id')
    config = get_site_config(comp_id)
    
    conn.close()
    
    return render_template('office/create_quote.html', 
                           clients=clients, 
                           pre_client=pre_client, 
                           brand_color=config['color'], 
                           logo_url=config['logo'],
                           settings=settings,
                           tax_rate=tax_rate)

# =========================================================
# 2. VIEW QUOTE
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>')
def view_quote(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    if request.args.get('mode') == 'pdf': 
        return redirect(url_for('pdf.download_quote_pdf', quote_id=quote_id)) 

    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT q.id, c.name, q.reference, q.date, q.total, q.status, q.expiry_date 
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

# =========================================================
# 3. CONVERT QUOTE TO JOB (The Bridge)
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>/book-job')
def convert_to_job(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')

    try:
        cur.execute("SELECT client_id, reference, total FROM quotes WHERE id = %s AND company_id = %s", (quote_id, comp_id))
        quote = cur.fetchone()
        
        if not quote: return "Quote not found", 404

        # Get first item for description
        cur.execute("SELECT description FROM quote_items WHERE quote_id = %s LIMIT 1", (quote_id,))
        item = cur.fetchone()
        desc = item[0] if item else "Work from Quote " + quote[1]

        job_ref = quote[1].replace('Q-', 'JOB-')
        
        cur.execute("""
            INSERT INTO jobs (company_id, client_id, ref, description, status, quote_id)
            VALUES (%s, %s, %s, %s, 'Accepted', %s)
            RETURNING id
        """, (comp_id, quote[0], job_ref, desc, quote_id))
        
        cur.execute("UPDATE quotes SET status = 'Accepted' WHERE id = %s", (quote_id,))
        
        conn.commit()
        flash(f"✅ Job {job_ref} Created! Check the Schedule.", "success")
        return redirect(url_for('office.office_calendar'))

    except Exception as e:
        conn.rollback()
        flash(f"Error converting to job: {e}", "error")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))
    finally:
        conn.close()

# =========================================================
# 4. EMAIL QUOTE
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>/email')
def email_quote(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    company_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT q.reference, c.name, c.email
        FROM quotes q JOIN clients c ON q.client_id = c.id
        WHERE q.id = %s AND q.company_id = %s
    """, (quote_id, company_id))
    q = cur.fetchone()
    
    if not q or not q[2]:
        conn.close()
        flash("❌ Client has no email address.", "error")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    ref, client_name, client_email = q[0], q[1], q[2]

    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if 'smtp_host' not in settings:
        conn.close()
        flash("⚠️ SMTP Settings missing. Configure them in Finance Settings.", "warning")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    cur.execute("SELECT description, quantity, unit_price, total FROM quote_items WHERE quote_id = %s", (quote_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    context = {'invoice': {'ref': ref, 'date': datetime.now()}, 'items': items, 'settings': settings, 'is_quote': True}
    filename = f"Quote_{ref}.pdf"
    
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        msg = MIMEMultipart()
        msg['From'] = settings.get('smtp_email')
        msg['To'] = client_email
        msg['Subject'] = f"Quote {ref} from {session.get('company_name')}"
        msg.attach(MIMEText(f"Dear {client_name},\n\nPlease find attached the quote {ref}.\n\nKind regards,", 'plain'))
        
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

# =========================================================
# 5. CONVERT TO INVOICE (With Dynamic Due Date)
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>/convert')
def convert_to_invoice(quote_id):
    if not check_access(): return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    comp_id = session.get('company_id')

    # 1. Fetch Quote Data
    cur.execute("SELECT client_id, total, status, reference FROM quotes WHERE id = %s AND company_id = %s", (quote_id, comp_id))
    quote = cur.fetchone()
    
    if not quote: return "Quote not found", 404
    if quote[2] == 'Converted':
        flash("⚠️ Already converted.", "warning")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))

    # 2. Get Payment Days Setting
    cur.execute("SELECT value FROM settings WHERE key = 'payment_days' AND company_id = %s", (comp_id,))
    res = cur.fetchone()
    days = int(res[0]) if res and res[0] else 14 # Default to 14 days if not set

    # 3. Create Invoice
    new_ref = f"INV-{quote[3]}" 
    try:
        # We inject the variable 'days' into the SQL interval
        cur.execute(f"""
            INSERT INTO invoices (company_id, client_id, ref, date_created, due_date, status, total_amount)
            VALUES (%s, %s, %s, CURRENT_DATE, CURRENT_DATE + INTERVAL '{days} days', 'Unpaid', %s)
            RETURNING id
        """, (comp_id, quote[0], new_ref, quote[1]))
        new_inv_id = cur.fetchone()[0]

        # 4. Copy Items
        cur.execute("""
            INSERT INTO invoice_items (invoice_id, description, quantity, unit_price, total)
            SELECT %s, description, quantity, unit_price, total
            FROM quote_items WHERE quote_id = %s
        """, (new_inv_id, quote_id))

        # 5. Update Quote Status
        cur.execute("UPDATE quotes SET status = 'Converted' WHERE id = %s", (quote_id,))
        conn.commit()
        
        flash(f"✅ Converted to Invoice {new_ref}", "success")
        return redirect(url_for('finance.finance_invoices'))
        
    except Exception as e:
        conn.rollback(); flash(f"Error: {e}", "error")
        return redirect(url_for('quote.view_quote', quote_id=quote_id))
    finally:
        conn.close()
        
        # =========================================================
# 6. PDF REDIRECT (The Fix for the 404 Button)
# =========================================================
@quote_bp.route('/office/quote/<int:quote_id>/pdf')
def pdf_redirect(quote_id):
    # This catches the old link and sends it to the new PDF engine
    return redirect(url_for('pdf.download_quote_pdf', quote_id=quote_id))