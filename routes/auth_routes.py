from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
import stripe
import os
from db import get_db
from werkzeug.security import check_password_hash, generate_password_hash
from email_service import send_company_email

auth_bp = Blueprint('auth', __name__)

# --- CRITICAL: Set the Stripe API Key ---
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# =========================================================
#  1. SIGN UP & STRIPE FLOW
# =========================================================

@auth_bp.route('/register', methods=['GET'])
def show_signup():
    conn = get_db()
    cur = conn.cursor()
    
    # Fetch active plans from DB to populate the dropdown
    # We filter out any test plans that might have price=0 if you want
    cur.execute("SELECT id, name, price FROM plans WHERE price > 0 ORDER BY price ASC")
    rows = cur.fetchall()
    conn.close()
    
    # Format for the template
    plans = [{'id': r[0], 'name': r[1], 'price': r[2]} for r in rows]
    
    return render_template('publicbb/signup.html', plans=plans)

@auth_bp.route('/process-signup', methods=['POST'])
def process_signup():
    # 1. Capture Form Data
    raw_plan_id = request.form.get('plan_id')
    
    data = {
        'company_name': request.form.get('company_name'),
        'sub_domain': request.form.get('sub_domain', '').lower().strip(),
        'company_type': request.form.get('company_type'),
        'owner_name': request.form.get('owner_name'),
        'owner_email': request.form.get('owner_email'),
        'password': request.form.get('password'),
        'plan_id': int(raw_plan_id) if raw_plan_id and raw_plan_id.isdigit() else None
    }

    conn = get_db()
    cur = conn.cursor()

    try:
        # 2. VALIDATE PLAN (With Debugging)
        if not data['plan_id']:
            flash("Error: No plan selected.", "error")
            return redirect(url_for('auth.show_signup'))

        # Simple Lookup
        cur.execute("SELECT id, name, price, stripe_price_id FROM plans WHERE id = %s", (data['plan_id'],))
        plan = cur.fetchone()

        # CRITICAL DEBUG: If not found, show us what IS in the DB
        if not plan:
            print(f"❌ ERROR: Database could not find Plan ID {data['plan_id']}")
            cur.execute("SELECT id, name FROM plans")
            all_plans = cur.fetchall()
            print(f"ℹ️ DATABASE SEES THESE PLANS: {all_plans}")
            
            flash(f"System Error: Plan ID {data['plan_id']} not recognized by database.", "error")
            return redirect(url_for('public.pricing'))

        # Plan Found - Extract Data
        plan_name = plan[1]
        plan_price = float(plan[2])
        stripe_price_id = plan[3]

        # 3. CHECK DUPLICATES
        cur.execute("SELECT id FROM users WHERE email = %s", (data['owner_email'],))
        if cur.fetchone():
            flash("That email is already registered. Please login.", "error")
            return redirect(url_for('auth.show_signup'))

        cur.execute("SELECT id FROM companies WHERE sub_domain = %s", (data['sub_domain'],))
        if cur.fetchone():
            flash(f"URL '{data['sub_domain']}' is already taken.", "error")
            return redirect(url_for('auth.show_signup'))

        # 4. PROCESS PAYMENT (OR SKIP IF FREE)
        if plan_price <= 0:
            # FREE PLAN LOGIC (No Stripe)
            # Create Company
            cur.execute("INSERT INTO companies (name, sub_domain, contact_email) VALUES (%s, %s, %s) RETURNING id", 
                       (data['company_name'], data['sub_domain'], data['owner_email']))
            company_id = cur.fetchone()[0]

            # Create User
            from werkzeug.security import generate_password_hash
            hashed_pw = generate_password_hash(data['password'])
            cur.execute("INSERT INTO users (email, password_hash, name, role, company_id, is_active) VALUES (%s, %s, %s, 'Admin', %s, true) RETURNING id",
                       (data['owner_email'], hashed_pw, data['owner_name'], company_id))
            
            # Create Sub
            import datetime
            now = datetime.datetime.now()
            cur.execute("INSERT INTO subscriptions (company_id, plan_id, status, start_date, renewal_date) VALUES (%s, %s, 'Active', %s, %s)",
                       (company_id, data['plan_id'], now, now + datetime.timedelta(days=3650)))
            
            conn.commit()
            return redirect(url_for('auth.signup_success'))

        else:
            # PAID PLAN LOGIC (Stripe)
            if not stripe_price_id:
                flash(f"Configuration Error: Plan '{plan_name}' has no Stripe Price ID.", "error")
                return redirect(url_for('auth.show_signup'))

            checkout_session = stripe.checkout.Session.create(
                payment_method_types=['card'],
                line_items=[{'price': stripe_price_id, 'quantity': 1}],
                mode='subscription',
                success_url=url_for('auth.signup_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
                cancel_url=url_for('auth.show_signup', _external=True),
                metadata={
                    'company_name': data['company_name'],
                    'sub_domain': data['sub_domain'],
                    'owner_name': data['owner_name'],
                    'owner_email': data['owner_email'],
                    'password': data['password'], # Note: We hash this later in the webhook
                    'plan_id': str(data['plan_id'])
                }
            )
            return redirect(checkout_session.url, code=303)

    except Exception as e:
        conn.rollback()
        print(f"SIGNUP EXCEPTION: {str(e)}")
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for('auth.show_signup'))
    finally:
        conn.close()

# =========================================================
#  2. LOGIN / LOGOUT
# =========================================================

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('auth.main_launcher'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        
        # Fetch user AND settings
        cur.execute("""
            SELECT u.id, u.name, u.password_hash, u.role, u.company_id, u.email,
                   s.value as status
            FROM users u 
            LEFT JOIN settings s ON u.company_id = s.company_id AND s.key = 'subscription_status'
            WHERE LOWER(TRIM(u.email)) = LOWER(TRIM(%s))
        """, (email,))
        
        user = cur.fetchone()
        
        if user and check_password_hash(user[2], password):
            # Check Status
            # SESSION SETUP
            session.permanent = True 
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[3]
            session['company_id'] = user[4]
            session['user_email'] = user[5] 
            
            # Load Modules (The Gatekeeper)
            cur.execute("SELECT modules FROM subscriptions WHERE company_id = %s", (user[4],))
            sub = cur.fetchone()
            session['modules'] = sub[0] if sub else ""

            # Log Audit
            ip = request.remote_addr
            cur.execute("INSERT INTO audit_logs (company_id, admin_email, action, target, ip_address) VALUES (%s, %s, 'LOGIN', 'System', %s)", (user[4], user[5], ip))
            conn.commit()
            conn.close()
            
            return redirect(url_for('auth.main_launcher'))
        else:
            flash("❌ Invalid credentials", "error")
            conn.close()

    return render_template('publicbb/login.html')

@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("🔒 You have been logged out securely.")
    return redirect(url_for('auth.login'))

# =========================================================
#  3. LAUNCHER & PROFILES
# =========================================================

@auth_bp.route('/launcher')
def main_launcher():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db(); cur = conn.cursor()
    user_id = session.get('user_id')

    # A. CHECK CLOCK STATUS
    is_at_work = False
    
    cur.execute("""
        SELECT s.id 
        FROM staff s 
        JOIN users u ON LOWER(s.email) = LOWER(u.email) AND s.company_id = u.company_id
        WHERE u.id = %s
    """, (user_id,))
    staff_row = cur.fetchone()
    
    if staff_row:
        staff_id = staff_row[0]
        session['staff_id'] = staff_id
        
        cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        if cur.fetchone(): 
            is_at_work = True

    # B. FETCH FULL PROFILE
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_row[0] if staff_row else 0,))
    profile_data = cur.fetchone()
    
    my_profile = {}
    if profile_data:
        cols = [desc[0] for desc in cur.description]
        my_profile = dict(zip(cols, profile_data))

    conn.close()
    
    return render_template('main_launcher.html', 
                           role=session.get('role'), 
                           my_profile=my_profile,
                           is_at_work=is_at_work)

@auth_bp.route('/auth/update_profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        phone = request.form.get('phone')
        address = request.form.get('address')
        nok_name = request.form.get('nok_name')
        nok_relationship = request.form.get('nok_relationship')
        nok_phone = request.form.get('nok_phone')
        nok_address = request.form.get('nok_address')
        
        cur.execute("""
            UPDATE staff 
            SET phone = %s, address = %s,
                nok_name = %s, nok_relationship = %s, nok_phone = %s, nok_address = %s
            WHERE email = (SELECT email FROM users WHERE id = %s)
            AND company_id = %s
        """, (phone, address, nok_name, nok_relationship, nok_phone, nok_address, session['user_id'], session['company_id']))
        
        conn.commit()
        flash("✅ Profile updated successfully.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"Error updating profile: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('auth.main_launcher'))

@auth_bp.route('/auth/change-password', methods=['POST'])
def change_password():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    user_id = session.get('user_id')
    old_pass = request.form.get('current_password')
    new_pass = request.form.get('new_password')
    confirm_pass = request.form.get('confirm_password')
    
    if new_pass != confirm_pass:
        flash("❌ New passwords do not match.", "error")
        return redirect(request.referrer)
        
    conn = get_db(); cur = conn.cursor()
    
    # 1. Verify Old Password
    cur.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
    user_row = cur.fetchone()
    
    if not user_row or not check_password_hash(user_row[0], old_pass):
        conn.close()
        flash("❌ Current password is incorrect.", "error")
        return redirect(request.referrer)
    
    # 2. Update to New Password
    new_hash = generate_password_hash(new_pass)
    cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user_id))
    conn.commit(); conn.close()
    
    flash("✅ Password updated successfully!", "success")
    return redirect(request.referrer)

@auth_bp.route('/auth/email/test')
def test_email_connection():
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        flash("❌ Access Denied", "error")
        return redirect(url_for('finance.settings_general'))
    
    comp_id = session.get('company_id')
    user_email = session.get('user_email') 
    
    success, msg = send_company_email(
        comp_id,
        user_email,
        "Test Email: Connection Successful",
        f"""
        <h1>It Works! 🚀</h1>
        <p>Your SMTP email settings are configured correctly.</p>
        <p><strong>Company:</strong> {session.get('company_name')}</p>
        <p>This email was sent directly from your own server to {user_email}.</p>
        """
    )
    
    if success:
        flash(f"✅ Success! Test email sent to {user_email}", "success")
    else:
        flash(f"❌ Connection Failed: {msg}", "error")
        
    return redirect(url_for('finance.settings_general'))

def create_pending_account(data):
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # A. Create Company (Status: Pending)
        cur.execute("""
            INSERT INTO companies (name, subdomain, contact_email, created_at)
            VALUES (%s, %s, %s, NOW()) RETURNING id
        """, (data['company_name'], data['sub_domain'], data['owner_email']))
        company_id = cur.fetchone()[0]

        # B. Create Owner User (Login Access)
        hashed_pw = generate_password_hash(data['password'], method='scrypt')
        cur.execute("""
            INSERT INTO users (email, password_hash, name, role, company_id, created_at)
            VALUES (%s, %s, %s, 'Admin', %s, NOW())
        """, (data['owner_email'], hashed_pw, data['owner_name'], company_id))

        # --- FIX 1: Create Owner Staff Profile (HR Record) ---
        # This ensures you appear in the "Staff" list immediately
        cur.execute("""
            INSERT INTO staff 
            (company_id, name, email, position, dept, phone, status, is_active, access_level)
            VALUES (%s, %s, %s, 'Owner', 'Management', '', 'Active', 1, 'Admin')
        """, (company_id, data['owner_name'], data['owner_email']))
        # -------------------------------------------------------

        # C. Define Modules & Limits Based on Plan
        if data['plan_id'] == 'sole-trader':
            modules = "Estimates,Invoices,Fleet,Portal,ServiceDesk,WhiteLabel"
            max_users = 2; max_vehicles = 2; max_storage = 5
        elif data['plan_id'] == 'growing':
            modules = "Estimates,Invoices,Fleet,Portal,ServiceDesk,WhiteLabel,RAMS,AutoCalc,Compliance,Projects"
            max_users = 10; max_vehicles = 10; max_storage = 20
        elif data['plan_id'] == 'agency':
            modules = "ServiceDesk,Portal,WhiteLabel,Compliance,Invoices"
            max_users = 5; max_vehicles = 0; max_storage = 10
        elif data['plan_id'] == 'enterprise':
            modules = "Estimates,Invoices,Fleet,Portal,ServiceDesk,WhiteLabel,RAMS,AutoCalc,Compliance,Projects"
            max_users = 20; max_vehicles = 20; max_storage = 100
        else:
            raise ValueError(f"CRITICAL: Unknown Plan ID '{data['plan_id']}'")

        # D. Map Plan ID (Strict Mode)
        plan_mapping = {'sole-trader': 1, 'growing': 2, 'agency': 3, 'enterprise': 4}
        if data['plan_id'] not in plan_mapping:
             raise ValueError(f"CRITICAL: Plan '{data['plan_id']}' has no ID mapping.")
        db_plan_id = plan_mapping[data['plan_id']]

        # E. Insert Subscription
        cur.execute("""
            INSERT INTO subscriptions 
            (company_id, plan_id, modules, max_users, max_vehicles, max_storage, status, start_date)
            VALUES (%s, %s, %s, %s, %s, %s, 'Pending_Payment', NOW())
        """, (company_id, db_plan_id, modules, max_users, max_vehicles, max_storage))

        # --- FIX 2: Set Settings (Including Company Name) ---
        layout = 'agency' if data['company_type'] == 'Agency' else 'trade'
        
        settings = [
            (company_id, 'company_name', data['company_name']), # <--- POPULATES SETTINGS PAGE
            (company_id, 'company_email', data['owner_email']),
            (company_id, 'company_type', data['company_type']),
            (company_id, 'dashboard_layout', layout),
            (company_id, 'brand_color', '#c5a059'),
            (company_id, 'subscription_status', 'Pending_Payment')
        ]
        cur.executemany("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s)", settings)

        conn.commit()
        return company_id

    except Exception as e:
        conn.rollback()
        print(f"DB Error: {e}")
        raise e 
    finally:
        conn.close()
        
@auth_bp.route('/signup-success')
def signup_success():
    # This renders the success HTML file you already created
    return render_template('publicbb/signup_success.html')