import os
import traceback
from flask import Flask, render_template, request, session
from werkzeug.exceptions import HTTPException  # <--- ADDED THIS IMPORT
from db import get_db

# 1. Import all Blueprints
from routes.portal_routes import portal_bp
from routes.public_routes import public_bp
from routes.auth_routes import auth_bp
from routes.office_routes import office_bp
from routes.compliance_routes import compliance_bp
from routes.client_routes import client_bp
from routes.finance_routes import finance_bp
from routes.admin_routes import admin_bp
from routes.site_routes import site_bp
from routes.pdf_routes import pdf_bp
from routes.plans import plans_bp
from routes.hr_routes import hr_bp
from routes.transactions import transactions_bp
from routes.job_routes import jobs_bp
from routes.quote_routes import quote_bp

# 2. CREATE THE APP
app = Flask(__name__)

# Configuration
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads', 'logos')

# 3. REGISTER BLUEPRINTS
app.register_blueprint(portal_bp)
app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(office_bp)
app.register_blueprint(compliance_bp)
app.register_blueprint(client_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(site_bp)
app.register_blueprint(pdf_bp)
app.register_blueprint(plans_bp)
app.register_blueprint(hr_bp)
app.register_blueprint(transactions_bp)
app.register_blueprint(jobs_bp)
app.register_blueprint(quote_bp)

# =========================================================
# GLOBAL ERROR CAPTURE (The "Black Box")
# This catches crashes and writes them to your Admin Log
# =========================================================
@app.errorhandler(Exception)
def handle_exception(e):
    # 1. Pass through standard HTTP errors (like 404 Page Not Found)
    if isinstance(e, HTTPException):
        return e

    # 2. Capture the Crash Details
    tb = traceback.format_exc()
    err_msg = str(e)
    route = request.path
    
    print(f"🚨 CRITICAL ERROR at {route}: {err_msg}") 
    
    # 3. Save to Database (system_logs table)
    try:
        conn = get_db()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_logs (level, message, traceback, route, created_at)
                VALUES ('CRITICAL', %s, %s, %s, CURRENT_TIMESTAMP)
            """, (err_msg, tb, route))
            conn.commit()
            conn.close()
    except Exception as db_err:
        print(f"❌ LOGGING FAILED: {db_err}")

    # 4. Show a friendly error page
    return "<h1>500 Internal Server Error</h1><p>The system administrator has been notified.</p>", 500

# --- DEBUG ROUTE ---
@app.route('/debug-files')
def debug_files():
    output = "<h1>File System Debug</h1>"
    root_dir = os.path.join(os.getcwd(), 'templates')
    for root, dirs, files in os.walk(root_dir):
        level = root.replace(root_dir, '').count(os.sep)
        indent = '&nbsp;' * 4 * (level)
        output += f"{indent}<b>{os.path.basename(root)}/</b><br>"
        subindent = '&nbsp;' * 4 * (level + 1)
        for f in files:
            output += f"{subindent}{f}<br>"
    return output

# --- SYSTEM BROADCAST CONTEXT PROCESSOR ---
@app.context_processor
def inject_global_alert():
    alert_msg = None
    try:
        conn = get_db()
        if conn:
            cur = conn.cursor()
            try:
                cur.execute("SELECT value FROM system_settings WHERE key = 'global_alert'")
                row = cur.fetchone()
                if row and row[0]: 
                    alert_msg = row[0]
            except: pass
            conn.close()
    except: pass
    
    return dict(global_system_alert=alert_msg)

# --- GLOBAL CURRENCY INJECTOR ---
@app.context_processor
def inject_currency():
    default_sym = '£'
    if 'company_id' not in session:
        return dict(currency_symbol=default_sym)
    
    try:
        if 'currency_symbol' in session:
            return dict(currency_symbol=session['currency_symbol'])
            
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session['company_id'],))
        row = cur.fetchone()
        conn.close()
        
        symbol = row[0] if row else default_sym
        session['currency_symbol'] = symbol
        return dict(currency_symbol=symbol)
        
    except Exception:
        return dict(currency_symbol=default_sym)

# --- GLOBAL BRANDING INJECTOR ---
@app.context_processor
def inject_branding():
    default_color = '#2c3e50'
    default_logo = None
    
    if 'company_id' not in session:
        return dict(brand_color=default_color, logo=default_logo)

    color = session.get('brand_color')
    logo = session.get('logo')

    if not color or not logo:
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("""
                SELECT key, value FROM settings 
                WHERE company_id = %s AND key IN ('brand_color', 'logo')
            """, (session['company_id'],))
            row_dict = dict(cur.fetchall())
            conn.close()
            
            color = row_dict.get('brand_color', default_color)
            logo = row_dict.get('logo')
            
            session['brand_color'] = color
            session['logo'] = logo
        except Exception:
            pass

    return dict(brand_color=color or default_color, logo=logo)

# --- TEMPORARY DATABASE CLEANUP TOOL ---
@client_bp.route('/debug/cleanup-tables')
def cleanup_tables():
    # Security: Only Admin can run this
    if session.get('role') not in ['Admin', 'SuperAdmin']: return "Unauthorized", 403
    
    conn = get_db()
    cur = conn.cursor()
    log = []
    
    # These are the legacy tables causing conflicts with the new system
    tables_to_drop = [
        'job_photos',      # Legacy (We use job_evidence)
        'timesheets',      # Legacy (We use staff_timesheets)
        'vehicle_crew',    # Legacy (We use vehicle_crews)
        'vehicle_checks',  # Legacy (We use maintenance_logs)
        'job_items'        # Legacy (We use job_materials)
    ]
    
    try:
        for table in tables_to_drop:
            cur.execute(f"DROP TABLE IF EXISTS {table} CASCADE;")
            log.append(f"🗑️ DROPPED TABLE: {table}")
            
        # Also ensure job_evidence has the correct columns for Certs
        cur.execute("ALTER TABLE job_evidence ADD COLUMN IF NOT EXISTS file_type TEXT DEFAULT 'Site Photo';")
        cur.execute("ALTER TABLE job_evidence ADD COLUMN IF NOT EXISTS document_date DATE;")
        log.append("✅ UPDATED TABLE: job_evidence (Ready for Certificates)")

        conn.commit()
        return f"<h1>Database Cleaned & Upgraded</h1><pre>{chr(10).join(log)}</pre>"
        
    except Exception as e:
        conn.rollback()
        return f"Error: {e}"
    finally:
        conn.close()