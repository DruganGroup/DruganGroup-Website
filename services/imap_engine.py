import imaplib
import email
from email.header import decode_header
import psycopg2
from db import get_db
from utils.encryption import get_encryptor
import os
import json
from services.ai_assistant import get_openai_client # Assuming we might use AI

def decode_mime_words(s):
    if not s: return ""
    return u''.join(
        word.decode(encoding or 'utf8') if isinstance(word, bytes) else word
        for word, encoding in decode_header(s))

def fetch_emails(comp_id):
    conn = get_db()
    if not conn: return []
    cur = conn.cursor()
    
    # Check if table exists, create if not
    cur.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            msg_id VARCHAR(255),
            sender VARCHAR(255),
            subject VARCHAR(255),
            body TEXT,
            date TIMESTAMP,
            client_id INTEGER,
            status VARCHAR(50) DEFAULT 'Unread',
            UNIQUE(company_id, msg_id)
        )
    """)
    conn.commit()
    
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s AND key IN ('imap_server', 'imap_port', 'imap_user', 'imap_password')", (comp_id,))
    settings = {row[0]: row[1] for row in cur.fetchall()}
    
    if not settings.get('imap_server') or not settings.get('imap_user') or not settings.get('imap_password'):
        conn.close()
        return []

    encryptor = get_encryptor()
    password = encryptor.decrypt(settings.get('imap_password'))
    
    if not password:
        conn.close()
        return []
        
    try:
        mail = imaplib.IMAP4_SSL(settings.get('imap_server'), int(settings.get('imap_port', 993)))
        mail.login(settings.get('imap_user'), password)
        mail.select('inbox')
        
        status, messages = mail.search(None, 'ALL')
        email_ids = messages[0].split()
        
        fetched = []
        for e_id in email_ids[-10:]: # last 10
            status, msg_data = mail.fetch(e_id, '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg = email.message_from_bytes(response_part[1])
                    subject = decode_mime_words(msg['subject'])
                    sender = decode_mime_words(msg['from'])
                    msg_id = msg['Message-ID']
                    
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            content_type = part.get_content_type()
                            if content_type == "text/plain":
                                try:
                                    body = part.get_payload(decode=True).decode()
                                except:
                                    pass
                    else:
                        try:
                            body = msg.get_payload(decode=True).decode()
                        except:
                            pass
                            
                    # Extract email from sender string (e.g. "Name <email@dom.com>")
                    import re
                    sender_email = sender
                    match = re.search(r'<(.+?)>', sender)
                    if match:
                        sender_email = match.group(1)
                        
                    # Match client
                    cur.execute("SELECT id FROM clients WHERE company_id=%s AND email=%s", (comp_id, sender_email))
                    client_row = cur.fetchone()
                    client_id = client_row[0] if client_row else None
                    
                    try:
                        cur.execute("""
                            INSERT INTO emails (company_id, msg_id, sender, subject, body, date, client_id)
                            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
                            ON CONFLICT (company_id, msg_id) DO NOTHING
                        """, (comp_id, msg_id, sender, subject, body, client_id))
                        fetched.append({'subject': subject, 'sender': sender})
                    except Exception as e:
                        pass
        conn.commit()
        mail.logout()
    except Exception as e:
        print("IMAP Error:", e)
    finally:
        conn.close()
        
    return fetched

def analyze_email_intent(body, comp_id):
    # simple mock logic or using actual AI
    if "accept" in body.lower() and "quote" in body.lower():
        return True
    return False

def draft_email_response(body, comp_id):
    # mocked for now
    return "Thank you for your email. We will get back to you shortly."
