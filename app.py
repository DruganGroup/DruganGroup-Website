from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import os

app = Flask(__name__)
# SECURITY WARNING: Change this to a random secret in Render Environment Variables
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 

# --- DATABASE CONNECTION ---
# Render will provide this URL automatically when we set it up
DB_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DB_URL:
        return None
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"DB Connection Error: {e}")
        return None

# --- ROUTES ---

@app.route('/')
@app.route('/index.html')
def home():
    return render_template('index.html')

@app.route('/about.html')
def about():
    return render_template('about.html')

@app.route('/services.html')
def services():
    return render_template('services.html')

@app.route('/contact.html')
def contact():
    return render_template('contact.html')

@app.route('/forensics.html')
def forensics():
    return render_template('forensics.html')

@app.route('/pricing.html')
def pricing():
    return render_template('pricing.html')

@app.route('/features.html')
def features():
    return render_template('features.html')

@app.route('/tradecore.html')
def tradecore_landing():
    return render_template('tradecore.html')

# --- LOGIN LOGIC ---
@app.route('/login', methods=['GET', 'POST'])
@app.route('/login.html', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email') # Use .get() to avoid crashing if empty
        password = request.form.get('password')
        
        conn = get_db_connection()
        if not conn:
            flash('Database not connected. Please check configuration.')
            return render_template('login.html')
            
        cur = conn.cursor()
        
        # 1. Check if it's a CLIENT
        cur.execute("SELECT * FROM clients WHERE email = %s", (email,))
        client = cur.fetchone()
        
        if client:
            session['user_type'] = 'client'
            session['user_id'] = client[0]
            session['user_name'] = client[1]
            conn.close()
            return redirect(url_for('client_dashboard'))
            
        # 2. Check if it's STAFF
        cur.execute("SELECT * FROM users WHERE username = %s AND password_hash = %s", (email, password))
        staff = cur.fetchone()
        conn.close()
        
        if staff:
            session['user_type'] = 'staff'
            session['user_name'] = staff[1]
            return "Staff Dashboard (Coming Soon)"
        else:
            flash('Invalid credentials. Please try again.')
            return redirect(url_for('login'))

    return render_template('login.html')

@app.route('/client-portal')
def client_dashboard():
    if 'user_type' not in session or session['user_type'] != 'client':
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    if conn:
        cur = conn.cursor()
        # Fetch jobs for this specific client
        cur.execute("SELECT display_ref, site_address, status, total_price FROM jobs WHERE client_id = %s", (session['user_id'],))
        jobs = cur.fetchall()
        conn.close()
    else:
        jobs = []
    
    # We need a client_dashboard.html template for this to work.
    # For now, we reuse index or a placeholder if you haven't made one.
    return f"<h1>Welcome {session['user_name']}</h1><p>Active Jobs: {len(jobs)}</p>" 

# --- START SERVER ---
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)