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
    
    conn.close()
    return render_template('admin/plans.html', plans=plans)

# --- 2. CREATE & SYNC PLAN (THE AUTOMATION ENGINE) ---
@plans_bp.route('/admin/plans/save', methods=['POST'])
def save_plan():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    # 1. Capture Local Data
    name = request.form.get('name')
    try:
        price_val = float(request.form.get('price'))
    except:
        price_val = 0.0
        
    users = request.form.get('max_users') or 0
    vehicles = request.form.get('max_vehicles') or 0
    clients = request.form.get('max_clients') or 0
    props = request.form.get('max_properties') or 0
    storage = request.form.get('max_storage') or 0
    
    modules_list = request.form.getlist('modules')
    modules_json = json.dumps(modules_list)

    # 2. TALK TO STRIPE (The Magic Step)
    stripe_prod_id = None
    stripe_price_id = None
    
    try:
        if stripe.api_key:
            # A. Create Product on Stripe
            product = stripe.Product.create(name=name)
            stripe_prod_id = product.id
            
            # B. Create Price on Stripe (Amount is in pennies, e.g. £10.00 -> 1000)
            price_obj = stripe.Price.create(
                product=stripe_prod_id,
                unit_amount=int(price_val * 100), 
                currency='gbp',
                recurring={'interval': 'month'}
            )
            stripe_price_id = price_obj.id
            print(f"✅ Synced with Stripe: {stripe_price_id}")
        else:
            print("⚠️ Stripe Key Missing - Plan created locally only.")

    except Exception as e:
        flash(f"❌ Stripe Error: {str(e)}", "error")
        return redirect(url_for('plans.view_plans'))

    # 3. SAVE TO LOCAL DB (With Stripe IDs)
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO plans (
                name, price, max_users, max_vehicles, max_clients, max_properties, 
                max_storage, modules_enabled, stripe_product_id, stripe_price_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, price_val, users, vehicles, clients, props, storage, modules_json, stripe_prod_id, stripe_price_id))
        
        conn.commit()
        flash(f"✅ Plan '{name}' Created & Live on Stripe!", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"❌ DB Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('plans.view_plans'))

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
        conn.close()
        
    return redirect(url_for('plans.view_plans'))