from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
from werkzeug.security import check_password_hash
from email_service import send_company_email

auth_bp = Blueprint('auth', __name__)

# --- 1. STAFF & ADMIN LOGIN ---
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, send them to the launcher
    if 'user_id' in session:
        return redirect(url_for('auth.main_launcher'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        conn = get_db()
        cur = conn.cursor()
        # Check users table and join with staff to get real name
        cur.execute("""
            SELECT u.id, u.username, u.password_hash, u.role, u.company_id, s.name 
            FROM users u 
            LEFT JOIN staff s ON LOWER(TRIM(u.email)) = LOWER(TRIM(s.email)) 
            WHERE LOWER(TRIM(u.username)) = LOWER(TRIM(%s))
        """, (email,))
        
        user = cur.fetchone()
        conn.close()

        if user and check_password_hash(user[2], password):
            session['user_id'] = user[0]
            session['username'] = user[1]
            session['user_email'] = user[2]
            session['role'] = user[3]
            session['company_id'] = user[4]
            
            # STORE THE REAL NAME (User[5] is the name from the staff table)
            # If no staff record is found, it falls back to the username
            session['user_name'] = user[5] if user[5] else user[1] 
            
            return redirect(url_for('auth.main_launcher'))
        else:
            flash("❌ Invalid Staff Credentials")
            
    # Render the login page (ensure this template exists in templates/public/login.html)
    return render_template('public/login.html')

@auth_bp.route('/launcher')
def main_launcher():
    # 1. Security Check
    if 'user_id' not in session: 
        return redirect(url_for('auth.login'))
    
    # 2. REDIRECT SUPER ADMIN (User ID 1)
    if session.get('user_id') == 1:
        session['user_name'] = "Master Admin"
        session['company_name'] = "Business Better HQ"
        return redirect(url_for('admin.super_admin_dashboard'))

    # 3. FETCH USER PROFILE DATA (For the new modal)
    conn = get_db()
    cur = conn.cursor()
    
    # We try to find the staff record linked to the logged-in user's email
    cur.execute("""
        SELECT phone, address, next_of_kin_name, next_of_kin_phone 
        FROM staff 
        WHERE email = %s AND company_id = %s
    """, (session.get('user_email'), session.get('company_id')))
    
    row = cur.fetchone()
    conn.close()
    
    # Create a safe dictionary (handles missing data gracefully)
    my_profile = {
        'phone': row[0] if row else '',
        'address': row[1] if row else '',
        'nok_name': row[2] if row else '',
        'nok_phone': row[3] if row else ''
    }

    # 4. RENDER TEMPLATE WITH PROFILE DATA
    return render_template('main_launcher.html', 
                           role=session.get('role'), 
                           my_profile=my_profile)

@auth_bp.route('/auth/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # Auto-Upgrade: Ensure columns exist (Runs only once if needed)
        try:
            cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS next_of_kin_name TEXT")
            cur.execute("ALTER TABLE staff ADD COLUMN IF NOT EXISTS next_of_kin_phone TEXT")
            conn.commit()
        except:
            conn.rollback() # Columns likely exist already

        # Update the staff record
        cur.execute("""
            UPDATE staff 
            SET phone = %s, address = %s, next_of_kin_name = %s, next_of_kin_phone = %s
            WHERE email = %s AND company_id = %s
        """, (
            request.form.get('phone'),
            request.form.get('address'),
            request.form.get('nok_name'),
            request.form.get('nok_phone'),
            session.get('user_email'), # Ensure your session sets this on login!
            session.get('company_id')
        ))
        
        conn.commit()
        flash("✅ Profile details updated successfully.", "success")
        
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
    # 1. Security Check (Only Admin/Finance can test this)
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        flash("❌ Access Denied", "error")
        return redirect(url_for('finance.settings_general'))
    
    comp_id = session.get('company_id')
    user_email = session.get('user_email') # Send the test to the logged-in user
    
    # 2. Trigger the Email Service
    # We pass the company_id so the service looks up the SMTP details from the DB
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
    
    # 3. Handle Result
    if success:
        flash(f"✅ Success! Test email sent to {user_email}", "success")
    else:
        flash(f"❌ Connection Failed: {msg}", "error")
        
    # Redirect back to the Settings Page
    return redirect(url_for('finance.settings_general'))
    
    from werkzeug.security import check_password_hash, generate_password_hash

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