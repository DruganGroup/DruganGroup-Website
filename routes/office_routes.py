from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, send_file
from db import get_db, get_site_config
from datetime import datetime, date, timedelta
from services.enforcement import check_limit
from werkzeug.utils import secure_filename
import os
import secrets
import string
import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Custom Services
from services.pdf_generator import generate_pdf
try:
    from services.ai_assistant import scan_receipt, verify_license, universal_sort_document
except ImportError:
    scan_receipt = None; verify_license = None; universal_sort_document = None

office_bp = Blueprint('office', __name__)
ALLOWED_OFFICE_ROLES = ['Admin', 'SuperAdmin', 'Office', 'Manager']
UPLOAD_FOLDER = 'static/uploads/receipts'

# --- HELPER FUNCTIONS ---
def check_office_access():
    if 'user_id' not in session: return False
    if session.get('role') not in ALLOWED_OFFICE_ROLES: return False
    return True

def format_date(d, fmt_str='%d/%m/%Y'):
    if not d: return ""
    try:
        if isinstance(d, str): d = datetime.strptime(d, '%Y-%m-%d')
        return d.strftime(fmt_str)
    except: return str(d)

@office_bp.route('/office-hub')
def office_dashboard():
    # 1. Security Check
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    conn = get_db(); cur = conn.cursor()

    # 2. Main Counters
    cur.execute("SELECT COUNT(*) FROM clients WHERE company_id=%s AND status='Active'", (comp_id,))
    leads_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id=%s AND status='Pending'", (comp_id,))
    pending_quotes = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id=%s AND status='Scheduled'", (comp_id,))
    active_jobs = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id=%s AND status='Unpaid'", (comp_id,))
    unpaid_inv = cur.fetchone()[0]

    # 3. Upcoming Jobs (Next 5)
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, c.name, j.start_date, j.estimated_days, j.status 
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id 
        WHERE j.company_id = %s AND j.status IN ('Scheduled', 'In Progress') 
        ORDER BY j.start_date ASC LIMIT 5
    """, (comp_id,))
    upcoming_jobs = cur.fetchall()

    # 4. Recent Logs
    cur.execute("SELECT action, details, created_at FROM audit_logs WHERE company_id=%s ORDER BY created_at DESC LIMIT 5", (comp_id,))
    logs = [{'action': r[0], 'details': r[1], 'time': format_date(r[2], "%H:%M")} for r in cur.fetchall()]

    # 5. Dropdown Data (For the "Quick Actions" Modals)
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s ORDER BY name", (comp_id,))
    clients = cur.fetchall()
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id=%s AND status='Active'", (comp_id,))
    vehicles = cur.fetchall()

    # 6. Quote Pipeline
    cur.execute("SELECT status, COUNT(*), SUM(total) FROM quotes WHERE company_id=%s GROUP BY status", (comp_id,))
    pipe_raw = cur.fetchall()
    
    pipeline = {
        'Draft': {'count': 0, 'value': 0},
        'Sent': {'count': 0, 'value': 0},
        'Accepted': {'count': 0, 'value': 0},
        'Rejected': {'count': 0, 'value': 0}
    }
    
    for r in pipe_raw:
        status_key = r[0] 
        if status_key in pipeline:
            pipeline[status_key]['count'] = r[1]
            pipeline[status_key]['value'] = float(r[2] or 0)

    # 7. [FIX] SERVICE DESK COUNTER (This caused your 500 Error)
    # We try to count tickets. If the table doesn't exist yet, we default to 0 to prevent a crash.
    pending_requests = 0
    try:
        cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id=%s AND status='Pending'", (comp_id,))
        row = cur.fetchone()
        if row: pending_requests = row[0]
    except:
        # If table service_requests is missing, just ignore it for now
        pass

    conn.close()

    # 8. Render Template with ALL variables
    return render_template('office/office_dashboard.html',
                           brand_color=config['color'],
                           logo_url=config['logo'],
                           leads_count=leads_count,
                           pending_quotes=pending_quotes,
                           active_jobs=active_jobs,
                           unpaid_inv=unpaid_inv,
                           upcoming_jobs=upcoming_jobs,
                           logs=logs,
                           clients=clients,
                           vehicles=vehicles,
                           pipeline=pipeline,
                           pending_requests=pending_requests) # <--- Passed to HTML
# =========================================================
# 2. CALENDAR VIEW
# =========================================================
@office_bp.route('/office/calendar')
def office_calendar():
    if not check_office_access(): return redirect(url_for('auth.login'))
    comp_id = session.get('company_id')
    config = get_site_config(comp_id)
    return render_template('office/calendar.html', brand_color=config['color'], logo_url=config['logo'])

@office_bp.route('/api/calendar/events')
def get_calendar_events():
    if not check_office_access(): return jsonify([])
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    cur.execute("""
        SELECT j.id, j.ref, j.description, j.start_date, j.estimated_days, c.name, j.status 
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id 
        WHERE j.company_id = %s AND j.start_date IS NOT NULL
    """, (comp_id,))
    
    events = []
    for r in cur.fetchall():
        start = r[3]
        # Calculate End Date based on est_days
        end = start + timedelta(days=int(r[4] or 1))
        
        color = '#3788d8' # Default Blue
        if r[6] == 'Completed': color = '#28a745'
        elif r[6] == 'In Progress': color = '#ffc107'
        
        events.append({
            'id': r[0],
            'title': f"{r[1]} - {r[5]}",
            'start': start.isoformat(),
            'end': end.isoformat(),
            'color': color,
            'url': f"/office/job/{r[0]}/files"
        })
        
    conn.close()
    return jsonify(events)

# =========================================================
# 3. QUOTING SYSTEM
# =========================================================
@office_bp.route('/office/quote/new')
def new_quote():
    if not check_office_access(): return redirect(url_for('auth.login'))
    
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # 1. Get Client List
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s ORDER BY name", (comp_id,))
    clients = cur.fetchall()
    
    # 2. Get Saved Materials (for autocomplete)
    cur.execute("SELECT name, cost_price FROM materials WHERE company_id=%s", (comp_id,))
    materials = [{'name': r[0], 'price': r[1]} for r in cur.fetchall()]
    
    conn.close()
    return render_template('office/new_quote.html', clients=clients, materials=materials)