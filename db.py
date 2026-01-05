import psycopg2
import os

# Database Configuration
# 1. Try to get the Live URL (Render provides this)
DB_URL = os.environ.get("DATABASE_URL")

# Upload Configuration
UPLOAD_FOLDER = '/opt/render/project/src/static/uploads/logos'
if not os.path.exists('/opt/render/project/src'):
    # We are on Local Laptop
    UPLOAD_FOLDER = 'static/uploads/logos'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def get_db():
    try:
        if DB_URL:
            # --- OPTION A: LIVE (Render) ---
            conn = psycopg2.connect(DB_URL, sslmode='require')
        else:
            # --- OPTION B: LOCAL (Laptop) ---
            # This is where we tell it to use your new local DB
            conn = psycopg2.connect(
                dbname="businessbetter",  # <--- Your new DB name
                user="postgres",
                password="admin123",      # <--- The password you set in the SQL Shell
                host="localhost",
                port="5432"
            )
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

def get_site_config(comp_id):
    if not comp_id:
        return {"color": "#27AE60", "logo": "/static/images/logo.png"}
    
    conn = get_db()
    if not conn:
        return {"color": "#27AE60", "logo": "/static/images/logo.png"}
        
    cur = conn.cursor()
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    rows = cur.fetchall()
    conn.close()
    
    settings_dict = {row[0]: row[1] for row in rows}
    return {
        "color": settings_dict.get('brand_color', '#27AE60'),
        "logo": settings_dict.get('logo_url', '/static/images/logo.png')
    }

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS