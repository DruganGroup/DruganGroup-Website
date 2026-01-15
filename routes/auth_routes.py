from flask import Blueprint, render_template, request, session, redirect, url_for, flash
from db import get_db
from werkzeug.security import check_password_hash, generate_password_hash
from email_service import send_company_email

auth_bp = Blueprint('auth', __name__)

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
        
        # 1. FETCH USER (Your custom Email Search Logic)
        cur.execute("""
            SELECT u.id, u.name, u.password_hash, u.role, u.company_id, s.id, s.name 
            FROM users u 
            LEFT JOIN staff s ON LOWER(TRIM(u.email)) = LOWER(TRIM(s.email)) 
            WHERE LOWER(TRIM(u.email)) = LOWER(TRIM(%s))
        """, (email,))
        
        user = cur.fetchone()
        
        if user and check_password_hash(user[2], password):
            user_id = user[0]
            name = user[1]
            role = user[3]
            comp_id = user[4]
            staff_id = user[5]
            real_name = user[6]

            # --- AUTO-CREATE STAFF IF MISSING ---
            if not staff_id and role != 'SuperAdmin': 
                try:
                    cur.execute("""
                        INSERT INTO staff (company_id, name, email, phone, position, status, pay_rate)
                        VALUES (%s, %s, %s, '0000000000', 'Director', 'Active', 0.00)
                        RETURNING id, name
                    """, (comp_id, name, email))
                    
                    new_staff = cur.fetchone()
                    staff_id = new_staff[0]
                    real_name = new_staff[1]
                    conn.commit()
                except Exception as e:
                    conn.rollback()
                    print(f"Auto-Staff Error: {e}")
            # ---------------------------------------------

            # Set Session Data
            session['user_id'] = user_id
            session['username'] = name
            session['user_email'] = email 
            session['role'] = role
            session['company_id'] = comp_id
            session['user_name'] = real_name if real_name else name
            
            # SPECIAL HANDLE: SuperAdmin goes straight to dashboard
            if role == 'SuperAdmin':
                session['company_name'] = "HQ"
                session['logged_in'] = True
                conn.close()
                return redirect(url_for('admin.super_admin_dashboard'))

            conn.close()
            return redirect(url_for('auth.main_launcher'))
        else:
            conn.close()
            flash("❌ Invalid Credentials")
            
    host = request.host.lower()
    
    # 1. If on Business Better -> Show the new Software Login
    if 'businessbetter.co.uk' in host:
        return render_template('publicbb/login.html')

    # 2. If on Drugan Group -> Show your original Trade Login
    else:
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

    # 3. FETCH USER PROFILE DATA
    conn = get_db()
    cur = conn.cursor()
    
    # --- UPDATED QUERY: Pulls the new NOK columns ---
    cur.execute("""
        SELECT phone, address, nok_name, nok_phone, nok_relationship, nok_address 
        FROM staff 
        WHERE email = %s AND company_id = %s
    """, (session.get('user_email'), session.get('company_id')))
    
    row = cur.fetchone()
    conn.close()
    
    # Create a safe dictionary
    my_profile = {
        'phone': row[0] if row else '',
        'address': row[1] if row else '',
        'nok_name': row[2] if row else '',
        'nok_phone': row[3] if row else '',
        'nok_relationship': row[4] if row else '',
        'nok_address': row[5] if row else ''
    }

    # 4. RENDER TEMPLATE
    return render_template('main_launcher.html', 
                           role=session.get('role'), 
                           my_profile=my_profile)

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