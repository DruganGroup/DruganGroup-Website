from flask import Flask
import os

# Import the Blueprints
from routes.public_routes import public_bp
from routes.auth_routes import auth_bp
from routes.office_routes import office_bp
from routes.client_routes import client_bp
from routes.finance_routes import finance_bp
from routes.admin_routes import admin_bp

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

# Global Error Handler (Optional)
@app.errorhandler(404)
def page_not_found(e):
    return "<h1>404 Error</h1><p>Page not found. The route is likely missing in the Blueprint.</p>", 404

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)