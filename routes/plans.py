import stripe
import os
import json
from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db

plans_bp = Blueprint('plans', __name__)

# --- CONFIGURATION ---
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

# --- 1. VIEW PLANS (DASHBOARD) ---
@plans_bp.route('/admin/plans')
def view_plans():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    
    # Fetch Plans
    cur.execute("SELECT * FROM plans ORDER BY price ASC")
    plans = []
    if cur.description:
        cols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            p = dict(zip(cols, row))
            try:
                p['modules'] = json.loads(p['modules_enabled']) if p.get('modules_enabled') else []
            except:
                p['modules'] = []
            plans.append(p)
    
    pass
    return render_template('admin/plans.html', plans=plans)

# --- 2. CREATE & SYNC PLAN (THE AUTOMATION ENGINE) ---
@plans_bp.route('/admin/plans/save', methods=['POST'])
def save_plan():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    # 1. Get Form Data
    plan_id = request.form.get('plan_id') # <--- Check if this exists
    name = request.form.get('name')
    try: price_val = float(request.form.get('price'))
    except: price_val = 0.0
        
    users = request.form.get('max_users') or 0
    vehicles = request.form.get('max_vehicles') or 0
    clients = request.form.get('max_clients') or 0
    props = request.form.get('max_properties') or 0
    storage = request.form.get('max_storage') or 0
    
    modules_list = request.form.getlist('modules')
    modules_json = json.dumps(modules_list)

    conn = get_db()
    cur = conn.cursor()

    try:
        # 2. UPDATE EXISTING PLAN
        if plan_id:
            # First, get the old Stripe ID so we can update it
            cur.execute("SELECT stripe_price_id, stripe_product_id FROM plans WHERE id = %s", (plan_id,))
            old_plan = cur.fetchone()
            
            # Update Stripe Price (We create a NEW price object because Stripe doesn't let you change price amounts)
            new_stripe_price_id = old_plan[0]
            if stripe.api_key and old_plan[1]:
                try:
                    price_obj = stripe.Price.create(
                        product=old_plan[1],
                        unit_amount=int(price_val * 100),
                        currency='gbp',
                        recurring={'interval': 'month'}
                    )
                    new_stripe_price_id = price_obj.id
                except Exception as e:
                    print(f"Stripe Update Error: {e}")

            # Update Local DB
            cur.execute("""
                UPDATE plans SET 
                name=%s, price=%s, max_users=%s, max_vehicles=%s, 
                max_clients=%s, max_properties=%s, max_storage=%s, 
                modules_enabled=%s, stripe_price_id=%s
                WHERE id=%s
            """, (name, price_val, users, vehicles, clients, props, storage, modules_json, new_stripe_price_id, plan_id))
            
            flash(f"✅ Plan '{name}' Updated Successfully!", "success")

        # 3. CREATE NEW PLAN (Existing Logic)
        else:
            # ... (Your existing create logic here) ...
            # Copy your existing Stripe Create code here or leave it if you merge the logic.
            # Ideally, wrap the Stripe Create logic in a block like:
            stripe_prod_id = None
            stripe_price_id = None
            if stripe.api_key:
                product = stripe.Product.create(name=name)
                stripe_prod_id = product.id
                price_obj = stripe.Price.create(
                    product=stripe_prod_id,
                    unit_amount=int(price_val * 100), 
                    currency='gbp',
                    recurring={'interval': 'month'}
                )
                stripe_price_id = price_obj.id
            
            cur.execute("""
                INSERT INTO plans (
                    name, price, max_users, max_vehicles, max_clients, max_properties, 
                    max_storage, modules_enabled, stripe_product_id, stripe_price_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, price_val, users, vehicles, clients, props, storage, modules_json, stripe_prod_id, stripe_price_id))
            
            flash(f"✅ Plan '{name}' Created!", "success")

        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('plans.view_plans'))
    
@plans_bp.route('/admin/danger/reset-database')
def reset_database():
    # 1. Security Check: Only Super Admin can do this
    if session.get('role') != 'SuperAdmin':
        return "ACCESS DENIED: You must be a Super Admin to perform a system wipe."

    conn = get_db()
    cur = conn.cursor()

    try:
        # 2. PROTECT THE SUPER ADMIN
        # We set your company_id to NULL so you aren't deleted when we wipe the companies table.
        # We also ensure your email is exactly what you want it to be.
        target_email = 'admin@drugangroup.co.uk'
        
        # Check if you exist first
        cur.execute("SELECT id FROM users WHERE email = %s", (target_email,))
        if not cur.fetchone():
            return f"STOP! The account '{target_email}' does not exist yet. Create it or rename your current account first."

        # Detach you from any company (Safety measure)
        cur.execute("UPDATE users SET company_id = NULL WHERE email = %s", (target_email,))
        
        # 3. THE WIPE (Order is important because of links between tables)
        # We delete child data first, then parents.
        
        tables_to_wipe = [
            "job_notes", "jobs", "quotes", "invoices",       # Finance & Work
            "vehicle_checks", "vehicles",                    # Fleet
            "property_compliance", "properties", "clients",  # CRM
            "tickets", "staff_timesheets"                    # Service Desk & HR
        ]
        
        for table in tables_to_wipe:
            # We use 'TRUNCATE' or 'DELETE' depending on your DB, DELETE is safer for now.
            # We wrap in try/except in case a table doesn't exist yet.
            try:
                cur.execute(f"DELETE FROM {table}")
            except:
                pass 

        # 4. DELETE COMPANIES (This kills all tenant data)
        cur.execute("DELETE FROM companies")

        # 5. DELETE USERS (Everyone except YOU)
        cur.execute("DELETE FROM users WHERE email != %s", (target_email,))

        conn.commit()
        return f"""
            <h1 style='color:green; font-family:sans-serif;'>SYSTEM WIPED SUCCESSFULLY</h1>
            <p>All users, companies, and jobs have been deleted.</p>
            <p>The only survivor is: <strong>{target_email}</strong></p>
            <p><a href='/admin/plans'>Return to Admin Panel</a></p>
        """

    except Exception as e:
        conn.rollback()
        return f"<h1>ERROR during wipe: {str(e)}</h1>"
        
    finally:
        pass

# --- 3. DELETE PLAN (CLEAN UP) ---
@plans_bp.route('/admin/plans/delete/<int:plan_id>')
def delete_plan(plan_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    try:
        # Optional: Deactivate on Stripe first?
        # For now, we just remove it from your dashboard so nobody new can buy it.
        cur.execute("DELETE FROM plans WHERE id = %s", (plan_id,))
        conn.commit()
        flash("🗑️ Plan deleted from dashboard (Stripe remains active for existing users).", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        pass
        
    return redirect(url_for('plans.view_plans'))