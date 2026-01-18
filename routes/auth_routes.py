from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
from werkzeug.security import check_password_hash, generate_password_hash
from email_service import send_company_email

auth_bp = Blueprint('auth', __name__)

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
        # We explicitly select the email to save it to the session later
        cur.execute("""
            SELECT u.id, u.name, u.password_hash, u.role, u.company_id, u.email 
            FROM users u 
            WHERE LOWER(TRIM(u.email)) = LOWER(TRIM(%s))
        """, (email,))
        
        user = cur.fetchone()
        
        if user and check_password_hash(user[2], password):
            # 2. SAVE SESSION DATA (The Fix)
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['role'] = user[3]
            session['company_id'] = user[4]
            session['user_email'] = user[5] # <--- CRITICAL: Now we are sure this exists
            
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

    # 1. CHECK CLOCK STATUS (Robust Method)
    # We find the Staff ID by linking the User ID directly
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
        cur.execute("SELECT id FROM staff_attendance WHERE staff_id = %s AND clock_out IS NULL", (staff_id,))
        if cur.fetchone(): 
            is_at_work = True

    # 2. FETCH PROFILE
    cur.execute("SELECT * FROM staff WHERE id = %s", (staff_row[0] if staff_row else 0,))
    profile_data = cur.fetchone()
    
    # Safely convert to dictionary
    my_profile = {}
    if profile_data:
        cols = [desc[0] for desc in cur.description]
        my_profile = dict(zip(cols, profile_data))

    conn.close()
    
    return render_template('main_launcher.html', 
                           role=session.get('role'), 
                           my_profile=my_profile,
                           is_at_work=is_at_work)

@auth_bp.route('/auth/update-profile', methods=['POST'])
def update_profile():
    if 'user_id' not in session: return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # --- UPDATED SAVE LOGIC ---
        # Note: I removed the auto "ALTER TABLE" block here because 
        # we ran the /fix-nok-columns script separately. It is safer this way.
        
        cur.execute("""
            UPDATE staff 
            SET phone = %s, 
                address = %s, 
                nok_name = %s, 
                nok_phone = %s,
                nok_relationship = %s, 
                nok_address = %s
            WHERE email = %s AND company_id = %s
        """, (
            request.form.get('phone'),
            request.form.get('address'),
            request.form.get('nok_name'),
            request.form.get('nok_phone'),
            request.form.get('nok_relationship'),
            request.form.get('nok_address'),
            session.get('user_email'), 
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
    # 1. Security Check
    if session.get('role') not in ['Admin', 'SuperAdmin', 'Finance']:
        flash("❌ Access Denied", "error")
        return redirect(url_for('finance.settings_general'))
    
    comp_id = session.get('company_id')
    user_email = session.get('user_email') 
    
    # 2. Trigger the Email Service
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