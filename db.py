import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool

# Global connection pool
_db_pool = None

# --- THIS WAS MISSING ---
# We define the upload folder here so other files can import it
if os.path.exists('/opt/render/project/src'):
    UPLOAD_FOLDER = '/opt/render/project/src/static/uploads/logos'
else:
    UPLOAD_FOLDER = 'static/uploads/logos'

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

def _get_pool():
    global _db_pool
    if _db_pool is None:
        db_url = os.environ.get("DATABASE_URL")
        try:
            if db_url:
                _db_pool = SimpleConnectionPool(1, 10, db_url, sslmode='require')
            else:
                _db_pool = SimpleConnectionPool(
                    1, 10,
                    dbname=os.environ.get("DB_NAME", "businessbetter"),
                    user=os.environ.get("DB_USER", "postgres"),
                    password=os.environ.get("DB_PASSWORD", ""),
                    host=os.environ.get("DB_HOST", "localhost"),
                    port=os.environ.get("DB_PORT", "5432")
                )
        except Exception as e:
            import logging
            logging.error(f"DB Pool Initialization Error: {e}")
    return _db_pool

def get_db():
    from flask import g
    
    # Check if we already have a connection for this request
    if 'db_conn' in g and getattr(g.db_conn, 'closed', 1) != 0:
        # Connection was closed but still in g, remove it
        g.pop('db_conn', None)

    if 'db_conn' not in g:
        pool = _get_pool()
        if pool:
            try:
                g.db_conn = pool.getconn()
            except Exception as e:
                import logging
                logging.error(f"Error getting connection from pool: {e}")
                return None
        else:
            return None
            
    return g.db_conn
    
def close_db_connection(e=None):
    from flask import g
    conn = g.pop('db_conn', None)
    if conn is not None:
        pool = _get_pool()
        if pool:
            try:
                pool.putconn(conn)
            except Exception as ex:
                import logging
                logging.error(f"Error returning connection to pool: {ex}")
                # Fallback
                if getattr(conn, 'closed', 1) == 0:
                    conn.close()
        else:
            if getattr(conn, 'closed', 1) == 0:
                conn.close()

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

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS