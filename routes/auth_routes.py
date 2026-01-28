from flask import Blueprint, render_template, request, session, redirect, url_for, flash, jsonify
import stripe
from db import get_db
from werkzeug.security import check_password_hash, generate_password_hash
from email_service import send_company_email

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET'])
def show_signup():
    # Shows the HTML form above
    return render_template('publicbb/signup.html')

@auth_bp.route('/process-signup', methods=['POST'])
def process_signup():
    # 1. Capture Data
    data = {
        'company_name': request.form.get('company_name'),
        'sub_domain': request.form.get('sub_domain'),
        'company_type': request.form.get('company_type'),
        'owner_name': request.form.get('owner_name'),
        'owner_email': request.form.get('owner_email'),
        'password': request.form.get('password'), # Note: Will hash later
        'plan_id': request.form.get('plan_id')
    }

    # 2. VALIDATION CHECK (Crucial!)
    conn = get_db()
    cur = conn.cursor()
    
    # Check if Email exists
    cur.execute("SELECT id FROM users WHERE email = %s", (data['owner_email'],))
    if cur.fetchone():
        flash("❌ Email already registered. Please login.", "error")
        return redirect(url_for('auth.show_signup'))

    # Check if Subdomain exists
    cur.execute("SELECT id FROM companies WHERE sub_domain = %s", (data['sub_domain'],))
    if cur.fetchone():
        flash(f"❌ URL '{data['sub_domain']}' is already taken. Try another.", "error")
        return redirect(url_for('auth.show_signup'))
    
    conn.close()

    stripe_prices = {
        'sole-trader': 'price_1SuRCGFiYl53Yok9fFl5cZK2',  # £99 Plan
        'growing': 'price_1SuRDDFiYl53Yok9W2PRvPuB',      # £199 Plan
        'agency': 'price_1SuRCGFiYl53Yok9fFl5cZK2',       # (Optional: Using £99 for Agency trial for now)
        'enterprise': 'price_1SuRDDFiYl53Yok9W2PRvPuB'    # (Optional: Using £199 for Enterprise trial for now)
    }
    
    # Default to Growing plan if the ID is missing or wrong
    price_id = stripe_prices.get(data['plan_id'], stripe_prices['growing'])

    # 4. CREATE STRIPE CHECKOUT SESSION
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price': price_id,
                'quantity': 1,
            }],
            mode='subscription',
            success_url=url_for('auth.signup_success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('auth.show_signup', _external=True),
            
            # THE MAGIC: We stash the form data inside Stripe's "metadata"
            # Stripe will send this back to us after they pay
            metadata={
                'company_name': data['company_name'],
                'sub_domain': data['sub_domain'],
                'company_type': data['company_type'],
                'owner_name': data['owner_name'],
                'owner_email': data['owner_email'],
                # Security Note: We don't send raw passwords to Stripe metadata.
                # In a real production app, we'd cache this in Redis or a temp DB table.
                # For this MVP, we will create the account as "Pending" first.
            }
        )
        
        # 5. CREATE "PENDING" ACCOUNT IN DB (To save the password securely)
        # We save it now, but set status='Pending_Payment'
        create_pending_account(data) # <--- Helper function we write next
        
        return redirect(checkout_session.url, code=303)

    except Exception as e:
        flash(f"Payment Error: {str(e)}", "error")
        return redirect(url_for('auth.show_signup'))
        
def create_pending_account(data):
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # A. Create Company (Status: Pending)
        cur.execute("""
            INSERT INTO companies (name, sub_domain, contact_email, created_at)
            VALUES (%s, %s, %s, NOW()) RETURNING id
        """, (data['company_name'], data['sub_domain'], data['owner_email']))
        company_id = cur.fetchone()[0]

        # B. Create Owner User
        hashed_pw = generate_password_hash(data['password'], method='scrypt')
        cur.execute("""
            INSERT INTO users (email, password_hash, name, role, company_id, created_at)
            VALUES (%s, %s, %s, 'Admin', %s, NOW())
        """, (data['owner_email'], hashed_pw, data['owner_name'], company_id))

        # C. Set Settings (The Gatekeeper)
        # Default layout based on type
        layout = 'trade' if data['company_type'] == 'Trade' else 'agency'
        
        settings = [
            (company_id, 'company_type', data['company_type']),
            (company_id, 'dashboard_layout', layout),
            (company_id, 'brand_color', '#c5a059'), # Default Gold
            (company_id, 'subscription_status', 'Pending_Payment') # Important flag
        ]
        cur.executemany("INSERT INTO settings (company_id, key, value) VALUES (%s, %s, %s)", settings)

        conn.commit()
        return company_id

    except Exception as e:
        conn.rollback()
        print(f"DB Error: {e}")
    finally:
        conn.close()

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        return redirect(url_for('auth.main_launcher'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        
        # 1. FETCH USER
        cur.execute("""
            SELECT u.id, u.name, u.password_hash, u.role, u.company_id, u.email 
            FROM users u 
            WHERE LOWER(TRIM(u.email)) = LOWER(TRIM(%s))
        """, (email,))
        
        user = cur.fetchone()
        
        if user and check_password_hash(user[2], password):
            # --- SECURITY FIX: Enforce 12-Hour Session Timeout ---
            session.permanent = True 
            
            # 2. SAVE SESSION DATA
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[3]
            session['company_id'] = user[4]
            session['user_email'] = user[5] 
            
            # 3. LOG AUDIT
            ip = request.remote_addr
            cur.execute("INSERT INTO audit_logs (company_id, admin_email, action, target, ip_address) VALUES (%s, %s, 'LOGIN', 'System', %s)", (user[4], user[5], ip))
            conn.commit()
            conn.close()
            
            return redirect(url_for('auth.main_launcher'))
        else:
            flash("❌ Invalid credentials", "error")
            conn.close()

    return render_template('publicbb/login.html')

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
    
# --- 3. LOGOUT ---
@auth_bp.route('/logout')
def logout():
    session.clear()
    flash("🔒 You have been logged out securely.")
    return redirect(url_for('auth.login'))
    
# --- 4. SYSTEM: TEST EMAIL CONNECTION ---
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