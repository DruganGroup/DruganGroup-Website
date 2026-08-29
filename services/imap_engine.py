import imaplib
import email
from email.header import decode_header
import email.utils
from datetime import datetime
import re
from db import get_db
from utils.encryption import get_encryptor

def decode_mime_words(s):
    if not s:
        return ""
    try:
        decoded_fragments = decode_header(s)
        pieces = []
        for word, encoding in decoded_fragments:
            if isinstance(word, bytes):
                try:
                    pieces.append(word.decode(encoding or 'utf-8', errors='replace'))
                except Exception:
                    pieces.append(word.decode('latin-1', errors='replace'))
            else:
                pieces.append(str(word))
        return u''.join(pieces)
    except Exception:
        return str(s)

def _extract_body_from_message(msg):
    body_text = ""
    body_html = ""

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in content_disposition:
                continue

            charset = part.get_content_charset() or 'utf-8'
            payload = part.get_payload(decode=True)
            if not payload:
                continue

            try:
                decoded_str = payload.decode(charset, errors='replace')
            except Exception:
                decoded_str = payload.decode('latin-1', errors='replace')

            if content_type == "text/plain" and not body_text:
                body_text = decoded_str
            elif content_type == "text/html" and not body_html:
                body_html = decoded_str
    else:
        content_type = msg.get_content_type()
        charset = msg.get_content_charset() or 'utf-8'
        payload = msg.get_payload(decode=True)
        if payload:
            try:
                decoded_str = payload.decode(charset, errors='replace')
            except Exception:
                decoded_str = payload.decode('latin-1', errors='replace')

            if content_type == "text/plain":
                body_text = decoded_str
            else:
                body_html = decoded_str

    if body_text.strip():
        return body_text.strip()
    
    if body_html.strip():
        cleaned = re.sub(r'<br\s*/?>', '\n', body_html, flags=re.IGNORECASE)
        cleaned = re.sub(r'</p>', '\n\n', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<[^>]+>', '', cleaned)
        return re.sub(r'\n{3,}', '\n\n', cleaned).strip()

    return ""

def test_imap_connection(comp_id):
    """
    Tests connecting to the IMAP server with saved credentials for comp_id.
    Returns (success: bool, message: str).
    """
    conn = get_db()
    if not conn:
        return False, "Database connection error."
    cur = conn.cursor()
    
    cur.execute(
        "SELECT key, value FROM settings WHERE company_id = %s AND key IN ('imap_server', 'imap_port', 'imap_user', 'imap_password')",
        (comp_id,)
    )
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    server = settings.get('imap_server')
    user = settings.get('imap_user')
    raw_pass = settings.get('imap_password')
    port = int(settings.get('imap_port') or 993)
    
    if not server or not user or not raw_pass:
        return False, "IMAP server, username, or password is not configured in Settings."

    encryptor = get_encryptor()
    password = encryptor.decrypt(raw_pass) if raw_pass else None
    if not password:
        return False, "Could not decrypt IMAP password."
        
    try:
        if port == 993:
            mail = imaplib.IMAP4_SSL(server, port, timeout=10)
        else:
            mail = imaplib.IMAP4(server, port, timeout=10)
            try:
                mail.starttls()
            except Exception:
                pass
        mail.login(user, password)
        mail.logout()
        return True, "IMAP Connection Successful!"
    except Exception as e:
        return False, f"IMAP Connection Failed: {e}"

def fetch_emails(comp_id):
    """
    Fetches emails from the configured IMAP inbox for comp_id and stores them in DB.
    Returns a dict with {'success': bool, 'count': int, 'message': str, 'fetched': list}.
    """
    conn = get_db()
    if not conn:
        return {'success': False, 'count': 0, 'message': "Database connection failed.", 'fetched': []}
        
    cur = conn.cursor()
    
    # Ensure table exists
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
            status VARCHAR(50) DEFAULT 'Unread',
            folder VARCHAR(20) DEFAULT 'Inbox',
            UNIQUE(company_id, msg_id)
        )
    """)
    cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS folder VARCHAR(20) DEFAULT 'Inbox';")
    cur.execute("ALTER TABLE emails ADD COLUMN IF NOT EXISTS recipient VARCHAR(255);")
    conn.commit()
    
    cur.execute(
        "SELECT key, value FROM settings WHERE company_id = %s AND key IN ('imap_server', 'imap_port', 'imap_user', 'imap_password')",
        (comp_id,)
    )
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    server = settings.get('imap_server')
    user = settings.get('imap_user')
    raw_pass = settings.get('imap_password')
    port = int(settings.get('imap_port') or 993)
    
    if not server or not user or not raw_pass:
        return {
            'success': False,
            'count': 0,
            'message': "IMAP settings are not configured. Please enter your IMAP details in Finance > Settings > Integrations.",
            'fetched': []
        }

    encryptor = get_encryptor()
    password = encryptor.decrypt(raw_pass) if raw_pass else None
    
    if not password:
        return {
            'success': False,
            'count': 0,
            'message': "Could not decrypt IMAP password. Please re-enter your password in Finance > Settings.",
            'fetched': []
        }
        
    mail = None
    fetched = []
    try:
        if port == 993:
            mail = imaplib.IMAP4_SSL(server, port, timeout=15)
        else:
            mail = imaplib.IMAP4(server, port, timeout=15)
            try:
                mail.starttls()
            except Exception:
                pass
                
        mail.login(user, password)
        mail.select('INBOX', readonly=True)
        
        status, messages = mail.search(None, 'ALL')
        if not messages or not messages[0]:
            mail.logout()
            return {'success': True, 'count': 0, 'message': "No emails found in INBOX.", 'fetched': []}
            
        email_ids = messages[0].split()
        recent_ids = email_ids[-25:]
        
        for e_id in recent_ids:
            try:
                status, msg_data = mail.fetch(e_id, '(RFC822)')
                for response_part in msg_data:
                    if isinstance(response_part, tuple):
                        msg = email.message_from_bytes(response_part[1])
                        
                        subject = decode_mime_words(msg.get('subject', 'No Subject'))
                        sender_raw = decode_mime_words(msg.get('from', 'Unknown Sender'))
                        msg_id = msg.get('Message-ID') or f"imap-{e_id.decode()}-{int(datetime.now().timestamp())}"
                        
                        email_date = datetime.now()
                        if msg.get('Date'):
                            try:
                                parsed_date = email.utils.parsedate_to_datetime(msg.get('Date'))
                                if parsed_date:
                                    if parsed_date.tzinfo:
                                        email_date = parsed_date.astimezone().replace(tzinfo=None)
                                    else:
                                        email_date = parsed_date
                            except Exception:
                                pass
                                
                        body = _extract_body_from_message(msg)
                        
                        sender_email = sender_raw
                        match = re.search(r'<(.+?)>', sender_raw)
                        if match:
                            sender_email = match.group(1).strip()
                        else:
                            email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', sender_raw)
                            if email_match:
                                sender_email = email_match.group(0).strip()
                                
                        cur.execute(
                            "SELECT id FROM clients WHERE company_id = %s AND LOWER(email) = LOWER(%s) LIMIT 1",
                            (comp_id, sender_email)
                        )
                        client_row = cur.fetchone()
                        client_id = client_row[0] if client_row else None
                        
                        cur.execute("""
                            INSERT INTO emails (company_id, msg_id, sender, recipient, subject, body, date, client_id, status, folder)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'Unread', 'Inbox')
                            ON CONFLICT (company_id, msg_id) DO NOTHING
                            RETURNING id
                        """, (comp_id, msg_id, sender_raw, user, subject, body, email_date, client_id))
                        
                        inserted = cur.fetchone()
                        if inserted:
                            fetched.append({'id': inserted[0], 'subject': subject, 'sender': sender_raw})
            except Exception as item_err:
                print(f"⚠️ Error parsing email {e_id}: {item_err}")
                continue

        conn.commit()
        mail.logout()
        
        count = len(fetched)
        msg_text = f"Synced {count} new email(s) from IMAP." if count > 0 else "Inbox is up to date (no new unread emails)."
        return {'success': True, 'count': count, 'message': msg_text, 'fetched': fetched}
        
    except imaplib.IMAP4.error as imap_err:
        err_msg = f"IMAP Authentication / Server Error: {imap_err}"
        print(f"❌ {err_msg}")
        return {'success': False, 'count': 0, 'message': err_msg, 'fetched': []}
    except Exception as e:
        err_msg = f"IMAP Sync Failed: {e}"
        print(f"❌ {err_msg}")
        return {'success': False, 'count': 0, 'message': err_msg, 'fetched': []}

def analyze_email_intent(body, comp_id):
    if not body:
        return False
    lower_body = body.lower()
    positive_phrases = ["accept quote", "accepted the quote", "proceed with", "go ahead", "approved quote", "confirm quote", "accept the estimate"]
    return any(p in lower_body for p in positive_phrases)

def draft_email_response(body, comp_id):
    return "Thank you for getting in touch. We have received your message and will respond shortly.\n\nBest regards,\nThe Office Team"
