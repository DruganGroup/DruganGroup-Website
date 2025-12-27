from flask import Flask, render_template, request, redirect, url_for, session, flash
import psycopg2
import os

app = Flask(__name__)
# Secure secret key
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123") 

# --- DATABASE CONNECTION ---
DB_URL = os.environ.get("DATABASE_URL")

def get_db():
    try:
        conn = psycopg2.connect(DB_URL, sslmode='require')
        return conn
    except Exception as e:
        print(f"❌ DB Connection Error: {e}")
        return None

# --- MAIN STATIC PAGES ---
@app.route('/')
def home(): return render_template('index.html')

@app.route('/about')
@app.route('/about.html')
def about(): return render_template('about.html')

@app.route('/services')
@app.route('/services.html')
def services(): return render_template('services.html')

@app.route('/tradecore')
@app.route('/tradecore.html')
def tradecore(): return render_template('tradecore.html')

@app.route('/forensics')
@app.route('/forensics.html')
def forensics(): return render_template('forensics.html')

@app.route('/contact')
@app.route('/contact.html')
def contact(): return render_template('contact.html')

# --- SERVICE SUB-PAGES ---
@app.route('/roofing.html')
def roofing(): return render_template('roofing.html')

@app.route('/construction.html')
def construction(): return render_template('construction.html')

@app.route('/groundworks.html')
def groundworks(): return render_template('groundworks.html')

@app.route('/landscaping.html')
def landscaping(): return render_template('landscaping.html')

@app.route('/maintenance.html')
def maintenance(): return render_template('maintenance.html')

@app.route('/management.html')
def management(): return render_template('management.html')


# --- LOGIN SYSTEM ---
@app.route('/login', methods=['GET', 'POST'])
@app.route('/login.html', methods=['GET', 'POST']) 
def login():
    if request.method == 'POST':
        email_or_user = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        if not conn: 
            flash("System Error: Database Connection Failed")
            return render_template('login.html')
            
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT id, username, role, company_id 
                FROM users 
                WHERE (username = %s OR email = %s) AND password_hash = %s
            """, (email_or_user, email_or_user, password))
            user = cur.fetchone()
        except Exception as e:
            print(f"Query Error: {e}")
            user = None
        finally:
            conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[2]
            session['company_id'] = user[3]
            
            if user[2] == 'SuperAdmin':
                return redirect(url_for('super_admin_dashboard'))
            else:
                return redirect(url_for('main_launcher'))
        else:
            flash('Invalid Email or Password')

    return render_template('login.html')

# --- THE MAIN LAUNCHER (3 BUTTON MENU) ---
@app.route('/dashboard-menu')
def main_launcher():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('main_launcher.html', role=session.get('role'))


# --- CLIENT DASHBOARD (OFFICE HUB) ---
@app.route('/client-portal')
def client_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    company_id = session.get('company_id')
    
    conn = get_db()
    if not conn: return "DB Error"
    cur = conn.cursor()
    
    # Create tables if they don't exist yet
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            date DATE,
            type TEXT, 
            category TEXT, 
            description TEXT, 
            amount DECIMAL(10,2), 
            reference TEXT
        );
    """)
    conn.commit()

    # Calculate Totals
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    
    balance = income - expense

    # Get Recent Transactions
    cur.execute("""
        SELECT date, type, category, description, amount, reference 
        FROM transactions 
        WHERE company_id = %s 
        ORDER BY date DESC LIMIT 10
    """, (company_id,))
    transactions = cur.fetchall()
    
    conn.close()

    return render_template('client_dashboard.html', 
                           total_income=income, 
                           total_expense=expense, 
                           total_balance=balance,
                           transactions=transactions)


# --- FINANCE DASHBOARD ---
@app.route('/finance-dashboard')
def finance_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    if session.get('role') not in ['Admin', 'SuperAdmin']:
        return "Access Denied: You need Admin privileges to view Finance."

    company_id = session.get('company_id')
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            date DATE,
            type TEXT, category TEXT, description TEXT, amount DECIMAL(10,2), reference TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()

    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Income'", (company_id,))
    income = cur.fetchone()[0] or 0.0
    cur.execute("SELECT SUM(amount) FROM transactions WHERE company_id = %s AND type='Expense'", (company_id,))
    expense = cur.fetchone()[0] or 0.0
    balance = income - expense

    cur.execute("SELECT date, type, category, description, amount, reference FROM transactions WHERE company_id = %s ORDER BY date DESC LIMIT 20", (company_id,))
    transactions = cur.fetchall()
    
    cur.execute("SELECT name FROM companies WHERE id = %s", (company_id,))
    comp_row = cur.fetchone()
    session['company_name'] = comp_row[0] if comp_row else "My Company"

    conn.close()
    return render_template('finance_dashboard.html', total_income=income, total_expense=expense, total_balance=balance, transactions=transactions)


# --- HR & STAFF ROUTES ---
@app.route('/finance/hr')
def finance_hr():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            company_id INTEGER,
            name TEXT, position TEXT, dept TEXT, pay_rate DECIMAL(10,2), pay_model TEXT, access_level TEXT
        );
    """)
    conn.commit()

    cur.execute("SELECT id, name, position, dept, pay_rate, pay_model, access_level FROM staff WHERE company_id = %s ORDER BY name", (session.get('company_id'),))
    staff = cur.fetchall()
    conn.close()
    
    return render_template('finance_hr.html', staff=staff)

@app.route('/finance/hr/add', methods=['POST'])
def add_staff():
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    
    name = request.form.get('name')
    position = request.form.get('position')
    dept = request.form.get('dept')
    rate = request.form.get('rate') or 0
    model = request.form.get('model')
    access = request.form.get('access_level')
    comp_id = session.get('company_id')
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            INSERT INTO staff (company_id, name, position, dept, pay_rate, pay_model, access_level)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (comp_id, name, position, dept, rate, model, access))
        
        if access != "None":
            username = name.split(" ")[0].lower() + f"{comp_id}" # e.g. john51
            email_fake = f"{username}@tradecore.com"
            default_pass = "Password123!" 
            
            cur.execute("SELECT id FROM users WHERE username=%s", (username,))
            if not cur.fetchone():
                cur.execute("""
                    INSERT INTO users (username, email, password_hash, role, company_id)
                    VALUES (%s, %s, %s, %s, %s)
                """, (username, email_fake, default_pass, access, comp_id))
                flash(f"✅ Staff added! Login: {username} / Pass: {default_pass}")
            else:
                flash("✅ Staff added, but username already existed.")
        else:
            flash("✅ Staff added successfully.")
            
        conn.commit()
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}")
    finally:
        conn.close()
        
    return redirect(url_for('finance_hr'))

@app.route('/finance/hr/delete/<int:id>')
def delete_staff(id):
    if session.get('role') not in ['Admin', 'SuperAdmin']: return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM staff WHERE id = %s AND company_id = %s", (id, session.get('company_id')))
    conn.commit()
    conn.close()
    flash("Staff deleted.")
    return redirect(url_for('finance_hr'))


# --- SUPER ADMIN DASHBOARD ---
@app.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    if session.get('role') != 'SuperAdmin': return redirect(url_for('login'))
        
    conn = get_db()
    if not conn: return "Database Error"
    cur = conn.cursor()
    
    if request.method == 'POST':
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        owner_pass = request.form.get('owner_pass')
        plan = request.form.get('plan')
        
        try:
            cur.execute("INSERT INTO companies (name, contact_email) VALUES (%s, %s) RETURNING id", (comp_name, owner_email))
            new_company_id = cur.fetchone()[0]
            cur.execute("INSERT INTO subscriptions (company_id, plan_tier, status) VALUES (%s, %s, 'Active')", (new_company_id, plan))
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, 'Admin', %s)", (owner_email, owner_pass, owner_email, new_company_id))
            conn.commit()
            flash(f"✅ Success! {comp_name} created.")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    cur.execute("SELECT c.id, c.name, s.plan_tier, s.status, u.email FROM companies c LEFT JOIN subscriptions s ON c.id = s.company_id LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin' ORDER BY c.id DESC")
    companies = cur.fetchall()
    conn.close()
    return render_template('super_admin.html', companies=companies)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)