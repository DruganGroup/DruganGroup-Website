import os
import traceback
import time
from datetime import timedelta
from dotenv import load_dotenv
load_dotenv()
# Added 'g' to imports for White Label Logic
from flask import Flask, render_template, request, session, send_from_directory, abort, redirect, url_for, g, flash
from werkzeug.exceptions import HTTPException
from db import get_db
from utils.extensions import limiter, csrf

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
csrf.init_app(app)

# --- SECURITY: INITIALIZE RATE LIMITING ---
limiter.init_app(app)

# Configuration
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    # Strictly enforce SECRET_KEY in all environments for security
    raise RuntimeError("CRITICAL SECURITY ERROR: SECRET_KEY environment variable is missing and MUST be set in your .env file or host environment!")

app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static', 'uploads', 'logos')

# --- SECURITY: SESSION HARDENING (HTTPS ENABLED) ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=12)
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# 3. SECURITY HEADERS
@app.after_request
def set_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    
    # Only set HSTS in production
    if os.environ.get('FLASK_ENV') == 'production':
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    
    # Basic CSP - adjust as needed for your application
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://unpkg.com https://js.stripe.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://unpkg.com https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; "
        "img-src 'self' data: https:; "
        "connect-src 'self' https://api.stripe.com;"
    )
    
    return response

# 4. REGISTER BLUEPRINTS
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
# WHITE LABEL LOGIC (SUBDOMAIN INTERCEPTOR)
# =========================================================
@app.before_request
def load_tenant_context():
    """
    Runs before every request. Checks if the user is visiting via a subdomain
    (e.g., drugangroup.businessbetter.co.uk). If so, it loads that company's ID.
    """
    host = request.host.lower()
    
    # Allow overriding base domain via environment variable
    base_domain = os.environ.get('BASE_DOMAIN', 'businessbetter.co.uk')
    
    # 1. Check if we are on a subdomain (and NOT www)
    if base_domain in host and not host.startswith('www.') and host != base_domain:
        # Extract the subdomain (e.g. "drugangroup")
        subdomain = host.replace(f'.{base_domain}', '').split('.')[0]
        
        # 2. Look up the company in the DB
        conn = get_db()
        if conn:
            try:
                cur = conn.cursor()
                # Note: DB schema uses 'sub_domain' (with underscore)
                cur.execute("SELECT id, name FROM companies WHERE LOWER(sub_domain) = %s", (subdomain,))
                company = cur.fetchone()
                
                if company:
                    # Found them! Store in global 'g' for this request
                    g.tenant_id = company[0]
                    g.tenant_name = company[1]
                    g.is_white_label = True
                    
                    # ENFORCE TENANT ISOLATION: 
                    # If a user is logged in, ensure they actually belong to this subdomain's company
                    # Skip check for SuperAdmins or if they are impersonating
                    logged_in_company_id = session.get('company_id')
                    if logged_in_company_id and not session.get('is_impersonating') and session.get('role') != 'SuperAdmin':
                        if logged_in_company_id != g.tenant_id:
                            # They are logged in, but navigating to another company's subdomain
                            session.clear()
                            flash("Session expired due to invalid tenant access. Please log in again.", "danger")
                            return redirect(url_for('auth.login'))
                else:
                    # Subdomain exists in URL but not in DB -> 404
                    g.is_white_label = False
                    # Optional: abort(404) if you want to block invalid subdomains strictly
            except Exception as e:
                print(f"Subdomain Check Error: {e}")
                g.is_white_label = False
        else:
            g.is_white_label = False
    else:
        g.is_white_label = False

# =========================================================
# DATABASE TEARDOWN (PREVENT CONNECTION LEAKS)
# =========================================================
from db import close_db_connection
app.teardown_appcontext(close_db_connection)

# =========================================================
# GLOBAL ERROR CAPTURE
# =========================================================
@app.errorhandler(Exception)
def handle_exception(e):
    # 1. Gather Info
    ip = request.remote_addr
    user_id = session.get('user_id')
    company_id = session.get('company_id')
    route = request.path
    
    # 2. Determine Error Type
    if isinstance(e, HTTPException):
        code = e.code
        msg = f"{e.name}: {e.description}"
        tb = "HTTP Warning" 
    else:
        code = 500
        msg = str(e)
        tb = traceback.format_exc()

    # 3. Log to DB
    conn = get_db()
    if conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO system_logs 
                (level, message, traceback, route, created_at, ip_address, user_id, company_id, status_code)
                VALUES (%s, %s, %s, %s, NOW(), %s, %s, %s, %s)
            """, ('ERROR' if code==500 else 'WARNING', msg, tb, route, ip, user_id, company_id, code))
            conn.commit()
        except Exception as db_err:
            print(f"Failed to log error: {db_err}")
        finally:
            pass

    # 4. Return standard error page
    return render_template('error.html', error=e), code

# --- CONTEXT PROCESSORS ---
from utils.translations import get_translation, get_lang_direction

@app.context_processor
def inject_translations():
    # Default to English
    lang_code = 'en'
    
    # 1. Check Session (Logged in user)
    if 'company_id' in session:
        if 'lang_code' in session:
            lang_code = session['lang_code']
        else:
            try:
                conn = get_db(); cur = conn.cursor()
                cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'system_language'", (session['company_id'],))
                row = cur.fetchone(); pass
                lang_code = row[0] if row else 'en'
                session['lang_code'] = lang_code
            except:
                pass
    else:
        # Public website visitor
        if 'public_lang' in session:
            lang_code = session['public_lang']
                
    # 2. Provide the _ function and language direction to templates
    def translate(text):
        return get_translation(text, lang_code)
        
    return dict(_=translate, lang_dir=get_lang_direction(lang_code), current_lang=lang_code)

global_alert_cache = {'msg': None, 'last_fetched': 0}

@app.context_processor
def inject_global_alert():
    now = time.time()
    if now - global_alert_cache['last_fetched'] > 60: # 60 seconds cache
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
                pass
        except: pass
        global_alert_cache['msg'] = alert_msg
        global_alert_cache['last_fetched'] = now

    return dict(global_system_alert=global_alert_cache['msg'])

@app.context_processor
def inject_currency():
    default_sym = '£'
    if 'company_id' not in session: return dict(currency_symbol=default_sym)
    try:
        if 'currency_symbol' in session: return dict(currency_symbol=session['currency_symbol'])
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session['company_id'],))
        row = cur.fetchone(); pass
        symbol = row[0] if row else default_sym
        session['currency_symbol'] = symbol
        return dict(currency_symbol=symbol)
    except: return dict(currency_symbol=default_sym)

from db import get_site_config

@app.context_processor
def inject_branding():
    # Defaults
    default_color = '#c5a059' # Gold
    default_logo = '/static/images/logo.png' # Business Better Logo
    
    # 1. IF LOGGED IN (Office/Admin OR Client Portal)
    comp_id = session.get('company_id') or session.get('portal_company_id')
    if comp_id:
        try:
            config = get_site_config(comp_id)
            color = config.get('color') or default_color
            logo = config.get('logo') or default_logo
            name = config.get('name') or session.get('company_name') or 'My Company'
            email = config.get('email') or ''

            # Keep session in sync
            if 'company_id' in session:
                session['company_name'] = name
                session['brand_color'] = color
                session['logo_url'] = logo

            return dict(
                brand_color=color, 
                logo=logo,
                logo_url=logo,
                company_name=name,
                company_email=email
            )
        except:
            pass

    # 2. IF NOT LOGGED IN BUT ON SUBDOMAIN (Use Interceptor Data)
    if hasattr(g, 'is_white_label') and g.is_white_label:
        try:
            config = get_site_config(g.tenant_id)
            return dict(
                brand_color=config.get('color') or default_color,
                logo=config.get('logo') or default_logo,
                logo_url=config.get('logo') or default_logo,
                company_name=g.tenant_name, # Pass name for "Login to [Company]" text
                company_email=config.get('email') or ''
            )
        except:
            pass

    # 3. FALLBACK (Main Marketing Site)
    return dict(brand_color=default_color, logo=default_logo, logo_url=default_logo, company_name='Business Better', company_email='')

@app.context_processor
def inject_sidebar_alerts():
    comp_id = session.get('company_id')
    if not comp_id:
        return dict(pending_tickets_count=0, unread_emails_count=0)
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id = %s AND status NOT IN ('Completed', 'Cancelled', 'Resolved')", (comp_id,))
        pending_tickets = cur.fetchone()[0] or 0
        
        cur.execute("SELECT COUNT(*) FROM emails WHERE company_id = %s AND folder = 'Inbox' AND status = 'Unread'", (comp_id,))
        unread_emails = cur.fetchone()[0] or 0
        
        return dict(pending_tickets_count=pending_tickets, unread_emails_count=unread_emails)
    except Exception:
        return dict(pending_tickets_count=0, unread_emails_count=0)
    
@app.route('/uploads/<path:filename>')
def serve_uploads(filename):
    # --- 1. PUBLIC ACCESS (ALLOW LOGOS) ---
    # If the file is a logo, serve it immediately without checking login.
    # This fixes the Client Portal Login page issue.
    if 'logos/' in filename or 'logo' in filename.lower():
        upload_dir = os.path.join(app.root_path, 'static', 'uploads')
        return send_from_directory(upload_dir, filename)

    # --- 2. PRIVATE ACCESS (SECURITY CHECK) ---
    # For everything else (Invoices, Documents, etc.), require login.
    
    # Check for ANY valid session ID
    if not any(k in session for k in ['user_id', 'portal_client_id']):
        return "Access Denied", 403 

    # IDENTIFY THE COMPANY ID
    user_comp_id = session.get('company_id') or session.get('portal_company_id')
    
    if not user_comp_id:
        return "Company Identity Not Found", 403

    # VERIFY TENANT ISOLATION
    parts = filename.split('/')
    if parts[0].startswith('company_'):
        try:
            target_comp_id = int(parts[0].replace('company_', ''))
            # Block if IDs don't match (unless SuperAdmin)
            if int(user_comp_id) != target_comp_id and session.get('role') != 'SuperAdmin':
                return "Unauthorized Tenant Access", 403
        except ValueError:
            return "Invalid Path Structure", 400

    # LOCATE AND SERVE
    upload_dir = os.path.join(app.root_path, 'static', 'uploads')
    return send_from_directory(upload_dir, filename)