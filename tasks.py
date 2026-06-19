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
            'company_id': company_id,
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

        import re
        safe_client = re.sub(r'[^a-zA-Z0-9_-]', '_', inv[5] or 'Client')
        filename = f"Invoice_{safe_client}_{invoice_ref}.pdf"
        
        # GENERATE PDF
        pdf_path = generate_pdf('finance/pdf_invoice_template.html', context, filename)
        
        return {"status": "SUCCESS", "filename": filename, "pdf_path": pdf_path}
        
    except Exception as e:
        conn.rollback()
        return f"Error processing invoice: {str(e)}"
    finally:
        cur.close()
        conn.close()

from email_service import send_company_email
from celery import shared_task

@shared_task
def send_welcome_email_task(company_id, owner_email, owner_name, sub_domain):
    subject = "Welcome to Business Better! 🚀"
    login_url = f"https://{sub_domain}.businessbetter.co.uk/login"
    
    body = f"""
    <h3>Hi {owner_name},</h3>
    <p>Your Business Better workspace is ready to go!</p>
    <p>You can access your dashboard here: <a href="{login_url}">{login_url}</a></p>
    <br>
    <p><strong>Next Steps:</strong></p>
    <ul>
        <li>Log in with your email and the password you created during signup.</li>
        <li>Visit the 'Settings' tab to upload your company logo and customize your branding.</li>
        <li>Invite your team members to the platform.</li>
    </ul>
    <p>If you need any help, just open a support ticket from your launcher.</p>
    <p>Best regards,<br>The Business Better Team</p>
    """
    
    send_company_email(company_id, owner_email, subject, body)



@celery.task(name='tasks.send_system_email_task')
def send_system_email_task(smtp_settings, recipient, subject, body):
    """
    Background task to send an email using the SuperAdmin (system_settings) SMTP credentials.
    """
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        
        msg = MIMEMultipart()
        msg['From'] = smtp_settings['smtp_email']
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        port = int(smtp_settings.get('smtp_port', 587))
        host = smtp_settings['smtp_server']
        user = smtp_settings['smtp_email']
        password = smtp_settings.get('smtp_password')
        
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as server:
                if password:
                    server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                if password:
                    server.login(user, password)
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"Celery System Email Error: {e}")
        return False

@celery.task(name='tasks.send_staff_email_task')
def send_staff_email_task(smtp_settings, recipient, name, staff_role, temp_pass):
    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_settings['smtp_email']
        msg['To'] = recipient
        msg['Subject'] = "Welcome to Business Better Staff"
        body = f"Hello {name},\n\nYou have been added to the Business Better team as a {staff_role}.\nYour temporary password is: {temp_pass}\n\nPlease login and change your password."
        msg.attach(MIMEText(body, 'plain'))
        
        port = int(smtp_settings.get('smtp_port', 587))
        host = smtp_settings['smtp_server']
        user = smtp_settings['smtp_email']
        password = smtp_settings.get('smtp_password')
        
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as server:
                if password:
                    server.login(user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port) as server:
                server.starttls()
                if password:
                    server.login(user, password)
                server.send_message(msg)
        return True
    except Exception as e:
        print(f"Celery Email Error: {e}")
        return False
    

@celery.task(name='tasks.send_tenant_email_task')
def send_tenant_email_task(company_id, recipient_email, subject, body_html, attachment_path=None):
    """
    Universal background task to send an email using a specific tenant's SMTP credentials.
    """
    from db import get_db
    from utils.encryption import get_encryptor
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.application import MIMEApplication
    import os

    conn = get_db()
    if not conn:
        return "Failed to connect to database."

    try:
        cur = conn.cursor()
        
        # 1. Fetch this specific tenant's SMTP settings
        cur.execute("""
            SELECT key, value FROM settings 
            WHERE company_id = %s AND key IN ('smtp_host', 'smtp_port', 'smtp_email', 'smtp_password')
        """, (company_id,))
        
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        smtp_host = settings.get('smtp_host')
        smtp_port = settings.get('smtp_port')
        smtp_email = settings.get('smtp_email')
        raw_pass = settings.get('smtp_password')

        # Check if the tenant has actually configured their email
        if not all([smtp_host, smtp_port, smtp_email, raw_pass]):
            return f"Company {company_id} has incomplete SMTP settings. Email aborted."

        # 2. Decrypt the tenant's SMTP password
        encryptor = get_encryptor()
        smtp_password = encryptor.decrypt(raw_pass)

        # 3. Construct the Email
        msg = MIMEMultipart()
        msg['From'] = smtp_email
        msg['To'] = recipient_email
        msg['Subject'] = subject
        
        # Attach the HTML body
        msg.attach(MIMEText(body_html, 'html'))

        # 4. Handle Optional Attachments (e.g., Invoices or Quotes)
        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            msg.attach(part)

        # 5. Connect and Send (Dynamically handles SSL vs TLS)
        port = int(smtp_port)
        if port == 465:
            # Port 465 requires strict SSL from the start
            with smtplib.SMTP_SSL(smtp_host, port) as server:
                server.login(smtp_email, smtp_password)
                server.send_message(msg)
        else:
            # Ports 587 or 25 use TLS upgrading
            with smtplib.SMTP(smtp_host, port) as server:
                server.starttls()
                server.login(smtp_email, smtp_password)
                server.send_message(msg)

        return f"SUCCESS: Email sent to {recipient_email} from tenant {smtp_email}"

    except Exception as e:
        error_msg = f"Tenant Email Error (Company {company_id}): {str(e)}"
        print(error_msg)
        return error_msg
    finally:
        conn.close()