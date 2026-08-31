from db import get_db

def check_limit(company_id, limit_type):
    """
    Checks if a company has reached their plan limit for a specific resource.
    limit_type options: 'max_users', 'max_vehicles', 'max_clients', 'max_properties', 'max_storage'
    Returns: (Allowed (bool), Message (str))
    """
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Get the Company's Plan Limits (Fall back to default subscription if plan join fails)
        cur.execute("""
            SELECT COALESCE(p.max_users, s.max_users, 9999), 
                   COALESCE(p.max_vehicles, s.max_vehicles, 9999), 
                   COALESCE(p.max_clients, s.max_clients, 9999), 
                   COALESCE(p.max_properties, s.max_properties, 9999), 
                   COALESCE(p.max_storage, s.max_storage, 9999), 
                   COALESCE(p.name, s.plan_tier, 'Subscription')
            FROM subscriptions s
            LEFT JOIN plans p ON s.plan_id = p.id
            WHERE s.company_id = %s AND s.status IN ('Active', 'Trialing', 'trialing')
        """, (company_id,))
        
        plan = cur.fetchone()
        
        # If no active plan found, check if company exists
        if not plan:
            # If company has no subscription row yet, allow initial setup
            cur.execute("SELECT id FROM companies WHERE id = %s", (company_id,))
            if not cur.fetchone():
                return False, "❌ Company not found."
            return True, "OK"

        limits = {
            'max_users': plan[0],
            'max_vehicles': plan[1],
            'max_clients': plan[2],
            'max_properties': plan[3],
            'max_storage': plan[4],
            'plan_name': plan[5]
        }

        # 2. Check Current Usage based on the request type
        current_count = 0
        
        if limit_type == 'max_vehicles':
            cur.execute("SELECT COUNT(*) FROM vehicles WHERE company_id = %s", (company_id,))
            current_count = cur.fetchone()[0] or 0
            
        elif limit_type == 'max_clients':
            cur.execute("SELECT COUNT(*) FROM clients WHERE company_id = %s", (company_id,))
            current_count = cur.fetchone()[0] or 0
            
        elif limit_type == 'max_properties':
            cur.execute("SELECT COUNT(*) FROM properties WHERE company_id = %s", (company_id,))
            current_count = cur.fetchone()[0] or 0
            
        elif limit_type == 'max_users':
            cur.execute("SELECT COUNT(*) FROM staff WHERE company_id = %s AND status = 'Active'", (company_id,))
            current_count = cur.fetchone()[0] or 0

        # 3. Compare (0 or None or >= 9999 means UNLIMITED)
        limit_val = limits.get(limit_type)
        if limit_val is None or limit_val == 0 or limit_val >= 9999:
            return True, "OK"
        
        if current_count >= limit_val:
            resource_name = limit_type.replace('max_', '')
            return False, f"⚠️ Plan Limit Reached: Your {limits['plan_name']} plan allows up to {limit_val} {resource_name} (currently using {current_count}). Please upgrade your tier in Billing & Plans."
            
        return True, "OK"

    except Exception as e:
        print(f"Enforcement Error: {e}")
        return True, "OK"

