import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import os
import time
import uuid
from datetime import datetime
from db import get_db
from utils.encryption import get_encryptor

def record_sent_email(company_id, recipient_email, subject, body_html, sender_email=None):
    """
    Records an outgoing email in the tenant's 'Sent' folder within the emails table.
    """
    if not company_id or not recipient_email:
        return
    try:
        conn = get_db()
        if not conn:
            return
        cur = conn.cursor()
        
        # Ensure emails table and required columns exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id SERIAL PRIMARY KEY,
                company_id INTEGER,
                msg_id VARCHAR(255),
                sender VARCHAR(255),
                recipient VARCHAR(255),
                subject VARCHAR(255),
                body TEXT,
                date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                client_id INTEGER,
                status VARCHAR(50) DEFAULT 'Read',
                folder VARCHAR(20) DEFAULT 'Inbox',
                UNIQUE(company_id, msg_id)
            )
        """)
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS folder VARCHAR(20) DEFAULT 'Inbox';")
        cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS recipient VARCHAR(255);")
        
        # Match client_id if possible
        client_id = None
        if recipient_email:
            cur.execute(
                "SELECT id FROM clients WHERE company_id = %s AND LOWER(email) = LOWER(%s) LIMIT 1",
                (company_id, recipient_email.strip())
            )
            client_row = cur.fetchone()
            if client_row:
                client_id = client_row[0]
                
        msg_id = f"sent-{int(time.time())}-{uuid.uuid4().hex[:8]}"
        sender = sender_email or "You"
        
        cur.execute("""
            INSERT INTO emails (company_id, msg_id, sender, recipient, subject, body, date, client_id, status, folder)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Read', 'Sent')
            ON CONFLICT (company_id, msg_id) DO NOTHING
        """, (company_id, msg_id, sender, recipient_email, subject, body_html, datetime.now(), client_id))
        conn.commit()
    except Exception as e:
        print(f"⚠️ Error recording sent email in database: {e}")

def send_company_email(company_id, to_email, subject, body, pdf_path=None):
    """
    Fetches the specific SMTP credentials for the company and sends an email.
    Also automatically records the email in the tenant's Sent folder.
    """
    print(f"📧 Attempting to send email for Company ID: {company_id}...")

    # 1. Fetch Company Settings from DB
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
    rows = cur.fetchall()
    
    settings = {row[0]: row[1] for row in rows}
    
    # 2. Extract SMTP Details
    smtp_server = settings.get('smtp_host')
    smtp_port = settings.get('smtp_port')
    smtp_user = settings.get('smtp_email')
    
    encryptor = get_encryptor()
    raw_pass = settings.get('smtp_password')
    smtp_pass = encryptor.decrypt(raw_pass) if raw_pass else None

    # Debug print
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

    # 4. Attach PDF
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
        
        # Check if Port 465 (Requires direct SSL)
        if str(smtp_port) == '465':
            server = smtplib.SMTP_SSL(smtp_server, int(smtp_port))
        else:
            server = smtplib.SMTP(smtp_server, int(smtp_port))
            server.starttls()  # Secure the connection for 587/25
            
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        print("✅ Email sent successfully!")
        
        # Automatically record to Sent folder in DB
        record_sent_email(company_id, to_email, subject, body, smtp_user)
        
        return True, "Email sent successfully!"
    except Exception as e:
        print(f"❌ SMTP Error Raw: {repr(e)}") 
        return False, f"Email Failed: {repr(e)}"
