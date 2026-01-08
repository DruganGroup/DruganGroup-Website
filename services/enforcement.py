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
        # 1. Get the Company's Plan Limits
        cur.execute("""
            SELECT p.max_users, p.max_vehicles, p.max_clients, p.max_properties, p.max_storage, p.name
            FROM subscriptions s
            JOIN plans p ON s.plan_tier = p.name  -- Assuming plan_tier matches plan name
            WHERE s.company_id = %s AND s.status = 'Active'
        """, (company_id,))
        
        plan = cur.fetchone()
        
        # If no active plan found, block everything (Safety Net)
        if not plan:
            return False, "❌ No active subscription found. Please contact billing."

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
            current_count = cur.fetchone()[0]
            
        elif limit_type == 'max_clients':
            cur.execute("SELECT COUNT(*) FROM clients WHERE company_id = %s", (company_id,))
            current_count = cur.fetchone()[0]
            
        elif limit_type == 'max_properties':
            cur.execute("SELECT COUNT(*) FROM properties WHERE company_id = %s", (company_id,))
            current_count = cur.fetchone()[0]
            
        elif limit_type == 'max_users':
            cur.execute("SELECT COUNT(*) FROM staff WHERE company_id = %s AND status = 'Active'", (company_id,))
            current_count = cur.fetchone()[0]

        # 3. Compare
        limit_val = limits.get(limit_type, 0)
        
        if current_count >= limit_val:
            return False, f"⚠️ Limit Reached: Your {limits['plan_name']} plan allows {limit_val} {limit_type.replace('max_', '')}. You have {current_count}."
            
        return True, "OK"

    except Exception as e:
        print(f"Enforcement Error: {e}")
        # Fail safe: Allow if DB error, or Block? safely block.
        return False, f"System Error checking limits: {e}"
    finally:
        conn.close()