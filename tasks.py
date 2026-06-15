import os
import smtplib
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from celery_worker import celery
from db import get_db, get_site_config
from services.pdf_generator import generate_pdf
from utils.encryption import get_encryptor
from flask import current_app

@celery.task(name='tasks.generate_invoice_pdf_task')
def generate_invoice_pdf_task(invoice_id, company_id, company_name):
    """
    Background task to generate an invoice PDF.
    """
    conn = get_db()
    if not conn:
        return "Failed to connect to database"
        
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT i.id, i.reference, i.date, i.total, i.status, 
                   c.name, c.email, c.address
            FROM invoices i
            JOIN clients c ON i.client_id = c.id
            WHERE i.id = %s AND i.company_id = %s
        """, (invoice_id, company_id))
        
        inv = cur.fetchone()
        if not inv:
            return f"Invoice {invoice_id} not found."

        client_email = inv[6]
        invoice_ref = inv[1]

        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        encryptor = get_encryptor()
        raw_pass = settings.get('smtp_password')
        settings['smtp_password'] = encryptor.decrypt(raw_pass) if raw_pass else None

        if 'smtp_host' not in settings:
            return "SMTP Settings missing."

        cur.execute("SELECT description, quantity, unit_price, total FROM invoice_items WHERE invoice_id = %s", (invoice_id,))
        items = [{'desc': r[0], 'qty': r[1], 'price': r[2], 'total': r[3]} for r in cur.fetchall()]
        
        config = get_site_config(company_id)
        
        if config.get('logo') and config['logo'].startswith('/'):
            clean_path = config['logo'].lstrip('/')
            # Note: app.root_path requires Flask app context
            local_path = os.path.join(current_app.root_path, clean_path)
            if os.path.exists(local_path):
                config['logo'] = local_path

        total_val = float(inv[3]) if inv[3] else 0.0
        
        context = {
            'invoice': {
                'ref': inv[1], 'date': inv[2], 'due': inv[2],
                'client_name': inv[5], 'client_address': inv[7], 'client_email': inv[6],
                'total': total_val, 'subtotal': total_val, 'tax': 0.0,
                'currency_symbol': settings.get('currency_symbol', '£')
            },
            'company': {'name': company_name},
            'items': items, 
            'settings': settings, 
            'config': config 
        }

        filename = f"Invoice_{invoice_ref}.pdf"
        
        # GENERATE PDF
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        return {"status": "SUCCESS", "filename": filename, "pdf_path": pdf_path}
        
    except Exception as e:
        conn.rollback()
        return f"Error processing invoice: {str(e)}"
    finally:
        cur.close()
        conn.close()



@celery.task(name='tasks.send_staff_email_task')
def send_staff_email_task(smtp_settings, recipient, name, staff_role, temp_pass):
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_settings['smtp_email']
        msg['To'] = recipient
        msg['Subject'] = "Welcome to Business Better Staff"
        body = f"Hello {name},\n\nYou have been added to the Business Better team as a {staff_role}.\nYour temporary password is: {temp_pass}\n\nPlease login and change your password."
        msg.attach(MIMEText(body, 'plain'))
        
        # Use SMTP_SSL for Port 465 (FastHosts requirement)
        with smtplib.SMTP_SSL(smtp_settings['smtp_server'], int(smtp_settings['smtp_port'])) as server:
            server.login(smtp_settings['smtp_email'], smtp_settings['smtp_password'])
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Celery Email Error: {e}")
        return False