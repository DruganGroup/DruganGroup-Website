import os
import traceback
from flask import Flask, render_template, request, session
from db import get_db


# 1. Import all Blueprints (Just importing, not registering yet)
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

# 2. CREATE THE APP (This must happen before we use 'app')
app = Flask(__name__)

# Configuration
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'uploads', 'logos')

# 3. REGISTER BLUEPRINTS (Now 'app' exists, so this works!)
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
            cur.execute("SELECT value FROM system_settings WHERE key = 'global_alert'")
            row = cur.fetchone()
            if row and row[0]: 
                alert_msg = row[0]
            conn.close()
    except: pass
    
    return dict(global_system_alert=alert_msg)
    # --- GLOBAL CURRENCY INJECTOR ---
@app.context_processor
def inject_currency():
    # Default to Pound if no user is logged in
    default_sym = '£'
    
    if 'company_id' not in session:
        return dict(currency_symbol=default_sym)
    
    try:
        # Check if we already cached it in session (Optimization)
        if 'currency_symbol' in session:
            return dict(currency_symbol=session['currency_symbol'])
            
        # Otherwise, fetch from DB
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (session['company_id'],))
        row = cur.fetchone()
        conn.close()
        
        symbol = row[0] if row else default_sym
        
        # Save to session so we don't hit DB on every click
        session['currency_symbol'] = symbol
        return dict(currency_symbol=symbol)
        
    except Exception:
        return dict(currency_symbol=default_sym)
        
        # --- GLOBAL BRANDING INJECTOR (Multi-Tenant Safe) ---
@app.context_processor
def inject_branding():
    # Defaults
    default_color = '#2c3e50'
    default_logo = None
    
    # SAFETY CHECK: If no company is logged in, show defaults
    if 'company_id' not in session:
        return dict(brand_color=default_color, logo=default_logo)

    # 1. Try Session (Fast)
    color = session.get('brand_color')
    logo = session.get('logo')

    # 2. If missing, Check Database for THIS Company ID
    if not color or not logo:
        try:
            conn = get_db()
            cur = conn.cursor()
            # The 'WHERE company_id = %s' ensures we only get THIS company's data
            cur.execute("""
                SELECT key, value FROM settings 
                WHERE company_id = %s AND key IN ('brand_color', 'logo')
            """, (session['company_id'],))
            row_dict = dict(cur.fetchall())
            conn.close()
            
            color = row_dict.get('brand_color', default_color)
            logo = row_dict.get('logo')
            
            # Update session to keep it fast next time
            session['brand_color'] = color
            session['logo'] = logo
        except Exception:
            pass

    return dict(brand_color=color or default_color, logo=logo)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    # Turn DEBUG ON so we can see the error
    app.run(host='0.0.0.0', port=port, debug=True)
    
    # --- FIX FLEET DATABASE ---
@app.route('/fix-fleet-db')
def fix_fleet_db():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Add the missing tracking columns to the vehicles table
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS telematics_provider VARCHAR(50);")
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS tracking_device_id TEXT;")
        cur.execute("ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS tracker_url TEXT;")
        
        conn.commit()
        conn.close()
        return "✅ Success! Fleet database updated. The Fleet Manager will load now."
    except Exception as e:
        return f"❌ Error: {e}"