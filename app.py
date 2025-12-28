from flask import Flask
import os

# Import the blueprints
from routes.public_routes import public_bp
from routes.auth_routes import auth_bp
# We will import the others (finance, office, etc.) once you create those files

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 
app.config['UPLOAD_FOLDER'] = '/opt/render/project/src/static/uploads/logos'

# Register the Blueprints
app.register_blueprint(public_bp)
app.register_blueprint(auth_bp)

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)