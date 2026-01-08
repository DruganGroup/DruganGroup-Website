from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from db import get_db
import json

plans_bp = Blueprint('plans', __name__)

# --- VIEW ALL PLANS ---
@plans_bp.route('/admin/plans')
def view_plans():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    
    # 1. SMART MIGRATION: Auto-update table if columns are missing
    try:
        # Create table if it doesn't exist
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plans (
                id SERIAL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                price DECIMAL(10, 2) DEFAULT 0.00,
                max_users INTEGER DEFAULT 5,
                max_storage INTEGER DEFAULT 10,
                max_rows INTEGER DEFAULT 10000,
                max_vehicles INTEGER DEFAULT 0,
                max_clients INTEGER DEFAULT 10,
                max_properties INTEGER DEFAULT 20,
                modules_enabled TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        
        # Add new columns if they are missing (for existing tables)
        cols = ['max_vehicles', 'max_clients', 'max_properties']
        for c in cols:
            cur.execute(f"ALTER TABLE plans ADD COLUMN IF NOT EXISTS {c} INTEGER DEFAULT 0;")
        
        cur.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS modules_enabled TEXT DEFAULT '[]';")
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"DB Update Error: {e}")

    # 2. Fetch Plans
    cur.execute("SELECT * FROM plans ORDER BY price ASC")
    plans = []
    if cur.description:
        cols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            p = dict(zip(cols, row))
            # Parse the modules JSON string back into a list
            try:
                p['modules'] = json.loads(p['modules_enabled']) if p.get('modules_enabled') else []
            except:
                p['modules'] = []
            plans.append(p)
    
    conn.close()
    return render_template('admin/plans.html', plans=plans)

# --- SAVE NEW PLAN ---
@plans_bp.route('/admin/plans/save', methods=['POST'])
def save_plan():
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    # Basic Info
    name = request.form.get('name')
    price = request.form.get('price')
    
    # Limits
    users = request.form.get('max_users') or 0
    vehicles = request.form.get('max_vehicles') or 0
    clients = request.form.get('max_clients') or 0
    props = request.form.get('max_properties') or 0
    storage = request.form.get('max_storage') or 0
    rows = 50000 
    
    # Modules (Checkboxes)
    modules_list = request.form.getlist('modules')
    modules_json = json.dumps(modules_list)
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO plans (name, price, max_users, max_vehicles, max_clients, max_properties, max_storage, max_rows, modules_enabled)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (name, price, users, vehicles, clients, props, storage, rows, modules_json))
        conn.commit()
        flash(f"✅ Plan '{name}' created with modules: {', '.join(modules_list)}", "success")
    except Exception as e:
        conn.rollback()
        flash(f"❌ Error creating plan: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('plans.view_plans'))

# --- DELETE PLAN ---
@plans_bp.route('/admin/plans/delete/<int:plan_id>')
def delete_plan(plan_id):
    if session.get('role') != 'SuperAdmin': return "Access Denied"
    
    conn = get_db(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM plans WHERE id = %s", (plan_id,))
        conn.commit()
        flash("🗑️ Plan deleted.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('plans.view_plans'))
    
    # --- MASTER DATABASE FIXER (Safe to run multiple times) ---
@app.route('/master-db-fix')
def master_db_fix():
    try:
        conn = get_db()
        cur = conn.cursor()
        
        # 1. FIX JOBS: Add quote_id if missing
        cur.execute("""
            ALTER TABLE jobs 
            ADD COLUMN IF NOT EXISTS quote_id INTEGER REFERENCES quotes(id);
        """)
        
        # 2. FIX TRANSACTIONS: Add date if missing
        cur.execute("""
            ALTER TABLE transactions 
            ADD COLUMN IF NOT EXISTS date DATE DEFAULT CURRENT_DATE;
        """)

        # 3. FIX QUOTES: Add status if missing
        cur.execute("""
            ALTER TABLE quotes 
            ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'Draft';
        """)
        
        # 4. FIX CLIENTS: Add billing_address if missing
        cur.execute("""
            ALTER TABLE clients 
            ADD COLUMN IF NOT EXISTS billing_address TEXT;
        """)

        conn.commit()
        conn.close()
        return """
        <div style="text-align: center; padding: 50px; font-family: sans-serif;">
            <h1 style="color: green;">✅ Database Updated</h1>
            <p>All missing columns have been created.</p>
            <a href="/" style="background: #333; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Go Home</a>
        </div>
        """
    except Exception as e:
        return f"❌ Error: {e}"