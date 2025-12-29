from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db
import re # Needed for generating the subdomain

admin_bp = Blueprint('admin', __name__)

@admin_bp.route('/super-admin', methods=['GET', 'POST'])
def super_admin_dashboard():
    # Security Check
    if session.get('role') != 'SuperAdmin': 
        return redirect(url_for('auth.login'))
    
    conn = get_db()
    cur = conn.cursor()
    
    if request.method == 'POST':
        comp_name = request.form.get('company_name')
        owner_email = request.form.get('owner_email')
        owner_pass = request.form.get('owner_pass')
        plan = request.form.get('plan')
        
        # --- NEW: GENERATE SUBDOMAIN (DUPLICATE DEFENDER) ---
        # 1. Create base slug (e.g. "Nick's Co" -> "nicks-co")
        base_slug = re.sub(r'[^a-z0-9-]', '', comp_name.lower().replace(' ', '-'))
        base_slug = re.sub(r'-+', '-', base_slug).strip('-')
        
        # 2. Check for duplicates and append number if needed
        final_slug = base_slug
        counter = 1
        while True:
            # Check if this specific slug exists in the DB
            cur.execute("SELECT id FROM companies WHERE subdomain = %s", (final_slug,))
            if not cur.fetchone():
                break # It's unique!
            final_slug = f"{base_slug}-{counter}"
            counter += 1
        # -----------------------------------------------------

        try:
            # 1. Create Company (Now includes Subdomain)
            cur.execute("""
                INSERT INTO companies (name, contact_email, subdomain) 
                VALUES (%s, %s, %s) RETURNING id
            """, (comp_name, owner_email, final_slug))
            new_company_id = cur.fetchone()[0]
            
            # 2. Create Subscription
            cur.execute("INSERT INTO subscriptions (company_id, plan_tier, status) VALUES (%s, %s, 'Active')", (new_company_id, plan))
            
            # 3. Create Admin User
            cur.execute("INSERT INTO users (username, password_hash, email, role, company_id) VALUES (%s, %s, %s, 'Admin', %s)", 
                        (owner_email, owner_pass, owner_email, new_company_id))
            
            conn.commit()
            flash(f"✅ Success! {comp_name} created with address: {final_slug}.drugangroup.co.uk")
        except Exception as e:
            conn.rollback()
            flash(f"❌ Error: {e}")
            
    # Load List of Companies (Added Subdomain to view)
    cur.execute("""
        SELECT c.id, c.name, s.plan_tier, s.status, u.email, c.subdomain 
        FROM companies c 
        LEFT JOIN subscriptions s ON c.id = s.company_id 
        LEFT JOIN users u ON c.id = u.company_id AND u.role = 'Admin' 
        ORDER BY c.id DESC
    """)
    companies = cur.fetchall()
    conn.close()
    
    return render_template('super_admin.html', companies=companies)