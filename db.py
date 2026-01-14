import psycopg2
import os

# Database Configuration
DB_URL = os.environ.get("DATABASE_URL")

# --- THIS WAS MISSING ---
# We define the upload folder here so other files can import it
if os.path.exists('/opt/render/project/src'):
    UPLOAD_FOLDER = '/opt/render/project/src/static/uploads/logos'
else:
    UPLOAD_FOLDER = 'static/uploads/logos'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def get_db():
    try:
        if DB_URL:
            # --- LIVE (Render) ---
            conn = psycopg2.connect(DB_URL, sslmode='require')
        else:
            # --- LOCAL (Laptop) ---
            conn = psycopg2.connect(
                dbname="businessbetter",
                user="postgres",
                password="admin123",
                host="localhost",
                port="5432"
            )
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

def get_site_config(comp_id):
    # Default Config
    default_config = {
        "color": "#27AE60", 
        "logo": "/static/images/logo.png"
    }

    if not comp_id:
        return default_config
    
    conn = get_db()
    if not conn:
        return default_config
        
    try:
        cur = conn.cursor()
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
        rows = cur.fetchall()
        settings_dict = {row[0]: row[1] for row in rows}
        
        # This keeps the "logo" fix we added earlier
        return {
            "color": settings_dict.get('brand_color', '#27AE60'),
            "logo": settings_dict.get('logo', '/static/images/logo.png') 
        }
    except Exception as e:
        print(f"Config Error: {e}")
        return default_config
    finally:
        if conn: conn.close()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS