from flask import Blueprint, session, redirect, url_for, flash, send_file
from db import get_db, get_site_config
from services.pdf_generator import generate_pdf

pdf_bp = Blueprint('pdf', __name__)

# --- TAX RATE LOOKUP TABLE ---
# This ties the rate to the country code automatically.
COUNTRY_TAX_RATES = {
    'GB': 20.0, # United Kingdom
    'ES': 21.0, # Spain
    'FR': 20.0, # France
    'DE': 19.0, # Germany
    'IE': 23.0, # Ireland
    'US': 0.0,  # USA (Sales tax varies by state, usually added differently, defaulting to 0 for now)
}

@pdf_bp.route('/finance/invoice/<int:invoice_id>/download')
def download_invoice_pdf(invoice_id):
    # 1. Security Check
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance', 'Office']:
        return redirect(url_for('auth.login'))
        
    conn = get_db()
    cur = conn.cursor()
    comp_id = session.get('company_id')

    # 2. Fetch Invoice Details
    cur.execute("""
        SELECT i.id, i.ref, i.date_created, i.due_date, 
               c.name, c.address, c.email, i.total_amount, i.status
        FROM invoices i
        JOIN clients c ON i.client_id = c.id
        WHERE i.id = %s AND i.company_id = %s
    """, (invoice_id, comp_id))
    inv = cur.fetchone()
    
    if not inv:
        conn.close()
        flash("❌ Invoice not found.", "error")
        return redirect(url_for('finance.finance_invoices'))

    # 3. Fetch Line Items
    cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # 4. Fetch Company Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    # 5. AUTOMATED TAX LOGIC (The Fix)
    if inv[7] is None:
        flash("❌ Error: Invoice has no total amount.", "error")
        return redirect(url_for('finance.finance_invoices'))
    
    total_val = float(inv[7])
    
    # A. Check if Company is VAT Registered
    # It checks for 'vat_registered' (new key) or 'tax_enabled' (old key)
    is_vat_registered = settings.get('vat_registered', settings.get('tax_enabled', '0'))
    
    # B. Get Country Code (Default to UK 'GB' if missing)
    country_code = settings.get('country', 'GB').upper()

    # C. Determine the Rate
    if str(is_vat_registered).lower() in ['1', 'true', 'yes', 'on']:
        # Look up the rate based on the country
        user_rate = COUNTRY_TAX_RATES.get(country_code, 20.0) # Default to 20% if country unknown
    else:
        # Not VAT registered = 0% tax
        user_rate = 0.0

    # 6. Calculate Net/Tax Backwards
    divisor = 1 + (user_rate / 100)
    if divisor == 1:
        subtotal_val = total_val
        tax_val = 0.0
    else:
        subtotal_val = total_val / divisor
        tax_val = total_val - subtotal_val

    # 7. Prepare Context
    context = {
        'invoice': {
            'ref': inv[1], 
            'date': inv[2], 
            'due': inv[3],
            'client_name': inv[4], 
            'client_address': inv[5], 
            'client_email': inv[6],
            'subtotal': subtotal_val,
            'tax': tax_val,
            'total': total_val,
            'tax_rate_display': user_rate,
            'currency_symbol': settings.get('currency_symbol', '£')
        },
        'company': {'name': session.get('company_name')},
        'items': items,
        'settings': settings,
        'config': get_site_config(comp_id)
    }

    # 8. Generate
    filename = f"Invoice_{inv[1]}.pdf"
    try:
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        return send_file(pdf_path, as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"PDF Error: {e}")
        return f"PDF Generation Error: {e}"