from flask import Blueprint, session, redirect, url_for, flash, send_file
from db import get_db, get_site_config
from services.pdf_generator import generate_pdf

# Define the new Blueprint
pdf_bp = Blueprint('pdf', __name__)

# --- DOWNLOAD INVOICE PDF (Strict Professional Mode) ---
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
        # Note: We redirect back to finance.finance_invoices
        return redirect(url_for('finance.finance_invoices'))

    # 3. Fetch Line Items
    cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
    items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
    
    # 4. Fetch Company Settings
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    conn.close()

    # 5. STRICT TAX LOGIC
    if inv[7] is None:
        flash("❌ Error: Invoice has no total amount. Please recalculate.", "error")
        return redirect(url_for('finance.finance_invoices'))
    
    total_val = float(inv[7])
    raw_rate = settings.get('tax_rate', settings.get('vat_rate'))
    
    if raw_rate is None:
        flash("⚠️ Cannot Generate PDF: Tax Rate is missing in Settings. Go to Finance > Settings.", "error")
        return redirect(url_for('finance.settings_general'))

    try:
        user_rate = float(raw_rate)
    except ValueError:
        flash(f"⚠️ Configuration Error: Tax Rate '{raw_rate}' is not a valid number.", "error")
        return redirect(url_for('finance.settings_general'))

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