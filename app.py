import os
import traceback
from datetime import timedelta
from flask import Flask, render_template, request, session, send_from_directory, abort
from werkzeug.exceptions import HTTPException
from db import get_db
from flask_wtf.csrf import CSRFProtect

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

# --- SECURITY: INITIALIZE CSRF PROTECTION ---
csrf = CSRFProtect(app)

# Configuration
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123")
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads', 'logos')

# --- SECURITY: SESSION HARDENING (HTTPS ENABLED) ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

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
# GLOBAL ERROR CAPTURE
# =========================================================
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return e

    tb = traceback.format_exc()
    err_msg = str(e)
    route = request.path
    
    print(f"🚨 CRITICAL ERROR at {route}: {err_msg}") 
    
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

# --- CONTEXT PROCESSORS ---
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
                if row and row[0]: alert_msg = row[0]
            except: pass
            conn.close()
    except: pass
    return dict(global_system_alert=alert_msg)

@app.context_processor
def inject_currency():
    default_sym = '£'
    if 'company_id' not in session: return dict(currency_symbol=default_sym)
    try:
        if 'currency_symbol' in session: return dict(currency_symbol=session['currency_symbol'])
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session['company_id'],))
        row = cur.fetchone(); conn.close()
        symbol = row[0] if row else default_sym
        session['currency_symbol'] = symbol
        return dict(currency_symbol=symbol)
    except: return dict(currency_symbol=default_sym)

@app.context_processor
def inject_branding():
    default_color = '#2c3e50'; default_logo = None
    if 'company_id' not in session: return dict(brand_color=default_color, logo=default_logo)
    
    color = session.get('brand_color')
    logo = session.get('logo')

    if not color or not logo:
        try:
            conn = get_db(); cur = conn.cursor()
            cur.execute("SELECT key, value FROM settings WHERE company_id = %s AND key IN ('brand_color', 'logo')", (session['company_id'],))
            row_dict = dict(cur.fetchall()); conn.close()
            color = row_dict.get('brand_color', default_color)
            logo = row_dict.get('logo')
            session['brand_color'] = color; session['logo'] = logo
        except: pass
    return dict(brand_color=color or default_color, logo=logo)
    
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    # 1. GLOBAL AUTH CHECK (Must be logged in)
    if 'user_id' not in session and 'portal_client_id' not in session:
        abort(403) # Not logged in = No Access
    
    # 2. IDENTIFY THE USER'S COMPANY
    # We get the ID from the session (secure server-side storage)
    user_comp_id = session.get('company_id') or session.get('portal_company_id')
    if not user_comp_id:
        abort(403) # No valid company ID found

    # 3. STRICT ISOLATION CHECK
    # We expect filenames to look like: "company_15/job_evidence/photo.jpg"
    # We split the filename to look at the first folder.
    parts = filename.split('/')
    
    if parts[0].startswith('company_'):
        try:
            # Extract the Company ID from the folder name "company_15" -> 15
            target_comp_id = int(parts[0].replace('company_', ''))
            
            # THE WALL: If User's Company != Folder's Company -> BLOCK THEM
            if int(user_comp_id) != target_comp_id:
                # Exception: SuperAdmins can view all files
                if session.get('role') != 'SuperAdmin':
                    print(f"⛔ SECURITY ALERT: Company {user_comp_id} tried to access Company {target_comp_id}'s files.")
                    abort(403) 
                    
        except ValueError:
            # If folder name is malformed, block just in case
            abort(404)

    # 4. SERVE THE FILE (Only if they passed the checks)
    root_dir = os.path.dirname(os.path.abspath(__file__))
    upload_dir = os.path.join(root_dir, 'uploads')
    
    try:
        return send_from_directory(upload_dir, filename)
    except FileNotFoundError:
        return "File not found", 404

# --- ERROR HANDLERS ---
@app.errorhandler(404)
def page_not_found(e):
    return render_template('publicbb/404.html'), 404