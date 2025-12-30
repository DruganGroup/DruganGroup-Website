from flask import session, flash, redirect, url_for
from db import get_db

# --- DEFINE TIER LIMITS ---
# This is the "Rule Book" for your SaaS
TIER_RULES = {
    'Basic': {
        'can_use_smtp': False,       # Basic users cannot use custom SMTP
        'max_staff': 2,              # Limit staff members
        'can_use_api': False,
        'can_upload_logo': True
    },
    'Pro': {
        'can_use_smtp': True,        # Pro users UNLOCK SMTP
        'max_staff': 10,
        'can_use_api': False,
        'can_upload_logo': True
    },
    'Enterprise': {
        'can_use_smtp': True,        # Enterprise has everything
        'max_staff': 999,
        'can_use_api': True,
        'can_upload_logo': True
    }
}

# --- THE CHECK FUNCTION ---
def check_tier_access(feature_name):
    """
    Checks if the logged-in company has paid for a specific feature.
    Returns True if allowed, False if blocked.
    """
    company_id = session.get('company_id')
    if not company_id:
        return False # No company, no access

    conn = get_db()
    cur = conn.cursor()
    
    # 1. Get the Company's current Plan
    cur.execute("SELECT plan_tier FROM subscriptions WHERE company_id = %s", (company_id,))
    res = cur.fetchone()
    conn.close()

    if not res:
        return False # No subscription found

    current_tier = res[0] # e.g., 'Basic'

    # 2. Check the Rule Book
    # If the tier isn't in our list, default to strict rules (safety first)
    rules = TIER_RULES.get(current_tier, TIER_RULES['Basic'])
    
    return rules.get(feature_name, False)

# --- THE DECORATOR (For protecting Routes) ---
# You can put this above any route like: @requires_feature('can_use_smtp')
def requires_feature(feature_name):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if not check_tier_access(feature_name):
                flash(f"🔒 UPGRADE REQUIRED: This feature is only available on higher tiers.")
                return redirect(url_for('finance.finance_dashboard')) # Kick them back to dashboard
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator