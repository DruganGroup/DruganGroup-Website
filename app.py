from flask import Flask
import os

# Import the Blueprints from your new 'routes' folder
from routes.public_routes import public_bp
from routes.auth_routes import auth_bp
from routes.office_routes import office_bp
from routes.client_routes import client_bp
from routes.finance_routes import finance_bp
from routes.admin_routes import admin_bp

app = Flask(__name__)

# --- CONFIGURATION ---
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 

# Upload Folder Config (Persistent Disk)
UPLOAD_FOLDER = '/opt/render/project/src/static/uploads/logos'
if not os.path.exists('/opt/render/project/src'):
    UPLOAD_FOLDER = 'static/uploads/logos'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# --- REGISTER BLUEPRINTS ---
# This connects all your separate files to the main app
app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(office_bp)
app.register_blueprint(client_bp)
app.register_blueprint(finance_bp)
app.register_blueprint(admin_bp)


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)