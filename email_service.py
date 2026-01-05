import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
from db import get_db

def send_company_email(company_id, to_email, subject, body, pdf_path=None):
    """
    Fetches the specific SMTP credentials for the company and sends an email.
    """
    print(f"📧 Attempting to send email for Company ID: {company_id}...")

    # 1. Fetch Company Settings from DB
    conn = get_db()
    cur = conn.cursor()
    # We fetch ALL settings for this company to be safe
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    rows = cur.fetchall()
    conn.close()
    
    settings = {row[0]: row[1] for row in rows}
    
    # 2. Extract SMTP Details (THE FIX IS HERE)
    # Your DB saves it as 'smtp_host', so we must ask for 'smtp_host'
    smtp_server = settings.get('smtp_host')  # <--- CHANGED FROM 'smtp_server'
    smtp_port = settings.get('smtp_port')
    smtp_user = settings.get('smtp_email')
    smtp_pass = settings.get('smtp_password')

    # Debug print to prove what we found
    print(f"DEBUG FETCH: Host={smtp_server}, User={smtp_user}, Port={smtp_port}")

    if not all([smtp_server, smtp_port, smtp_user, smtp_pass]):
        print("❌ Error: Missing SMTP settings for this company.")
        return False, "Missing Email Settings. Please configure them in Finance > Settings."

    # 3. Construct Email
    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    # 4. Attach PDF (Keep your logic!)
    if pdf_path and os.path.exists(pdf_path):
        try:
            with open(pdf_path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(pdf_path))
                msg.attach(attach)
        except Exception as e:
            print(f"⚠️ Could not attach PDF: {e}")

    # 5. Connect and Send
    try:
        print(f"DEBUG: Connecting to {smtp_server}:{smtp_port}...")
        server = smtplib.SMTP(smtp_server, int(smtp_port))
        server.starttls()  # Secure the connection
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
        return True, "Email sent successfully!"
    except Exception as e:
        # repr(e) forces the technical error details to show, preventing empty {}
        print(f"❌ SMTP Error Raw: {repr(e)}") 
        return False, f"Email Failed: {repr(e)}"