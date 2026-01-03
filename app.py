import os
import traceback
from flask import Flask, render_template, request, session
from db import get_db

# 1. Import all Blueprints (Just importing, not registering yet)
from routes.portal_routes import portal_bp
from routes.public_routes import public_bp
from routes.auth_routes import auth_bp
from routes.office_routes import office_bp
from routes.client_routes import client_bp
from routes.finance_routes import finance_bp
from routes.admin_routes import admin_bp
from routes.site_routes import site_bp

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
app.register_blueprint(client_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(site_bp)

# --- NEW: "BLACK BOX" ERROR HANDLER ---
@app.errorhandler(Exception)
def handle_exception(e):
    # 1. If it's just a 404 (Page Not Found), handle it gently
    if hasattr(e, 'code') and e.code == 404:
        return "<h1>404 Error</h1><p>Page not found. Please check your URL.</p>", 404

    # 2. If it's a real CRASH (500), capture the details
    tb_str = traceback.format_exc()
    route = request.path
    method = request.method
    
    # 3. Save the Crash Report to your new 'system_logs' database table
    try:
        conn = get_db()
        if conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO system_logs (level, message, traceback, route)
                VALUES ('CRITICAL', %s, %s, %s)
            """, (str(e), tb_str, f"{method} {route}"))
            conn.commit()
            conn.close()
    except Exception as db_err:
        print(f"❌ CRITICAL: Failed to log error to DB: {db_err}")

    # 4. Show a professional error page to the user
    return f"""
        <div style="font-family: sans-serif; text-align: center; padding: 50px;">
            <h1>⚠️ System Error</h1>
            <p>Something went wrong. The administrators at <b>Business Better</b> have been notified.</p>
            <p>Error details have been recorded in the System Logs.</p>
            <a href="/" style="color: blue; text-decoration: underline;">Return Home</a>
        </div>
    """, 500

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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)