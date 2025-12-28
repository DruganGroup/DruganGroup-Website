from flask import Flask
import os

# Import the Blueprints
from routes.public_routes import public_bp
from routes.auth_routes import auth_bp
from routes.office_routes import office_bp
from routes.client_routes import client_bp
from routes.finance_routes import finance_bp
from routes.admin_routes import admin_bp
from routes.site_routes import site_bp

app = Flask(__name__)

# Configuration
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 
app.config['UPLOAD_FOLDER'] = '/opt/render/project/src/static/uploads/logos'

# REGISTER BLUEPRINTS (This is what makes the routes work!)
app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(office_bp)
app.register_blueprint(client_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(admin_bp)
app.register_blueprint(site_bp)

# Global Error Handler (Optional)
@app.errorhandler(404)
def page_not_found(e):
    return "<h1>404 Error</h1><p>Page not found. The route is likely missing in the Blueprint.</p>", 404
    
    # --- DEBUG ROUTE (DELETE AFTER FIXING) ---
@app.route('/debug-files')
def debug_files():
    output = "<h1>File System Debug</h1>"
    # Walk through the templates folder and list everything
    root_dir = os.path.join(os.getcwd(), 'templates')
    for root, dirs, files in os.walk(root_dir):
        level = root.replace(root_dir, '').count(os.sep)
        indent = '&nbsp;' * 4 * (level)
        output += f"{indent}<b>{os.path.basename(root)}/</b><br>"
        subindent = '&nbsp;' * 4 * (level + 1)
        for f in files:
            output += f"{subindent}{f}<br>"
    return output

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)