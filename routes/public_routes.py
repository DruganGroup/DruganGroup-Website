from flask import Blueprint, render_template, request
from db import get_db

# Create the Blueprint
public_bp = Blueprint('public', __name__)

# --- CONFIGURATION ---
DOMAIN_SOFTWARE = 'businessbetter.co.uk'

def is_bb(host):
    return DOMAIN_SOFTWARE in host or 'localhost' in host or '127.0.0.1' in host

# --- MAIN PAGES ---
@public_bp.route('/')
@public_bp.route('/index')
@public_bp.route('/index.html')
def home():
    host = request.host.lower()

    # 1. WHITE LABEL CHECK (Subdomain Logic)
    if 'businessbetter.co.uk' in host and host != 'businessbetter.co.uk' and not host.startswith('www.'):
        subdomain = host.split('.')[0]
        
        conn = get_db()
        cur = conn.cursor()
        
        # Find the company ID
        cur.execute("SELECT id, name FROM companies WHERE subdomain = %s OR sub_domain = %s", (subdomain, subdomain))
        company_data = cur.fetchone()
        
        if company_data:
            company_id = company_data[0]
            company_name = company_data[1]

            # --- ROBUST SETTINGS FETCH ---
            # Grab ALL settings for this company so we don't miss anything
            cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
            settings_rows = cur.fetchall()
            settings = dict(settings_rows) # Convert to dictionary { 'key': 'value' }
            conn.close()

            # Smart Lookup: Try 'brand_color' OR default to Gold
            brand_color = settings.get('brand_color', '#c5a059')

            # Smart Lookup: Try 'logo' OR 'company_logo' OR 'invoice_logo'
            logo_url = settings.get('logo') or settings.get('company_logo') or settings.get('invoice_logo')

            # Render the Portal
            return render_template('portal/client_login.html',
                                   company_id=company_id,
                                   company_name=company_name,
                                   brand_color=brand_color,
                                   logo_url=logo_url)
        
        conn.close()

    # 2. DEFAULT: SHOW MARKETING SITE
    if is_bb(host):
        return render_template('publicbb/index.html')
    else:
        return render_template('public/index.html')

@public_bp.route('/about')
@public_bp.route('/about.html')
def about():
    host = request.host.lower()
    
    if is_bb(host):
        return render_template('publicbb/about.html')
    else:
        return render_template('public/about.html')

@public_bp.route('/contact')
@public_bp.route('/contact.html')
def contact():
    host = request.host.lower()

    if is_bb(host):
        # Points to Business Better contact page
        return render_template('publicbb/contact.html') 
    else:
        # Points to Drugan Group contact page
        return render_template('public/contact.html')

@public_bp.route('/pricing')
def pricing():
    conn = get_db()
    cur = conn.cursor()
    
    # 1. Fetch ALL public plans (Price > 0)
    # We order by price so they appear Cheap -> Expensive
    cur.execute("SELECT * FROM plans WHERE price > 0 ORDER BY price ASC")
    
    plans = []
    if cur.description:
        cols = [desc[0] for desc in cur.description]
        for row in cur.fetchall():
            p = dict(zip(cols, row))
            
            # 2. Parse Modules to list
            try:
                import json
                p['modules'] = json.loads(p['modules_enabled']) if p.get('modules_enabled') else []
            except:
                p['modules'] = []
            
            plans.append(p)
    
    conn.close()
    
    # 3. Render the page with the live data
    return render_template('publicbb/pricing.html', plans=plans)

# --- FEATURES / SALES FUNNEL ROUTES ---

# 1. The Gateway (Who are you?)
@public_bp.route('/features')
def features():
    host = request.host.lower()
    if is_bb(host):
        return render_template('publicbb/features.html')
    else:
        return render_template('public/index.html')

# 2. For Tradesmen (Winning contracts)
@public_bp.route('/features/trade')
def features_trade():
    host = request.host.lower()
    if is_bb(host):
        return render_template('publicbb/features_trade.html')
    else:
        return render_template('public/index.html')

# 3. For Estate Agents (Service Desk)
@public_bp.route('/features/agents')
def features_agents():
    host = request.host.lower()
    if is_bb(host):
        return render_template('publicbb/features_agents.html')
    else:
        return render_template('public/index.html')

# 4. Comparison Page (Why Switch)
@public_bp.route('/comparison')
def comparison():
    host = request.host.lower()
    if is_bb(host):
        return render_template('publicbb/comparison.html')
    else:
        return render_template('public/index.html')

# 5. Demo Video Page
@public_bp.route('/demo')
def demo():
    host = request.host.lower()
    if is_bb(host):
        return render_template('publicbb/demo.html')
    else:
        return render_template('public/index.html')

# --- SHARED/TRADE ROUTES (Drugan Group) ---
@public_bp.route('/services')
@public_bp.route('/services.html')
def services():
    return render_template('public/services.html')

@public_bp.route('/businessbetter')
@public_bp.route('/businessbetter.html')
def business_better():
    # This remains the "About the software" page for your Trade site
    return render_template('public/businessbetter.html')

@public_bp.route('/forensics')
@public_bp.route('/forensics.html')
def forensics():
    return render_template('public/forensics.html')
    
@public_bp.route('/legal')
def legal():
    return render_template('publicbb/legal.html')

@public_bp.route('/login')
@public_bp.route('/login.html')
def login_page():
    host = request.host.lower()

    # Check domain to ensure the right login design is shown
    if is_bb(host):
        return render_template('publicbb/login.html')
    else:
        return render_template('public/login.html')

# --- SUB PAGES (DRUGAN GROUP) ---
@public_bp.route('/construction')
@public_bp.route('/construction.html')
def construction():
    return render_template('public/construction.html')

@public_bp.route('/roofing')
@public_bp.route('/roofing.html')
def roofing():
    return render_template('public/roofing.html')

@public_bp.route('/groundworks')
@public_bp.route('/groundworks.html')
def groundworks():
    return render_template('public/groundworks.html')

@public_bp.route('/landscaping')
@public_bp.route('/landscaping.html')
def landscaping():
    return render_template('public/landscaping.html')

@public_bp.route('/maintenance')
@public_bp.route('/maintenance.html')
def maintenance():
    return render_template('public/maintenance.html')

@public_bp.route('/management')
@public_bp.route('/management.html')
def management():
    return render_template('public/management.html')
    
@public_bp.route('/help')
def help_center():
    host = request.host.lower()
    if is_bb(host):
        return render_template('publicbb/help.html')
    else:
        # If trade site users need help, maybe redirect to contact or a different page
        return render_template('public/contact.html')

import stripe

@public_bp.route('/pay/invoice/<int:invoice_id>')
def pay_invoice(invoice_id):
    """
    Public route for an end-client to pay an invoice via Stripe.
    """
    conn = get_db()
    cur = conn.cursor()
    
    try:
        # 1. Fetch invoice details
        cur.execute("""
            SELECT i.company_id, i.total, i.reference, i.status, c.name, c.email
            FROM invoices i
            JOIN clients c ON i.client_id = c.id
            WHERE i.id = %s
        """, (invoice_id,))
        inv = cur.fetchone()
        
        if not inv:
            return "Invoice not found.", 404
            
        comp_id, total, ref, status, client_name, client_email = inv
        
        if status == 'Paid':
            return "This invoice has already been paid. Thank you!", 200
            
        # 2. Fetch the tenant's Stripe Secret Key
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'stripe_secret_key'", (comp_id,))
        stripe_row = cur.fetchone()
        if not stripe_row or not stripe_row[0]:
            return "Online payments are not configured for this company.", 400
            
        from utils.encryption import get_encryptor
        encryptor = get_encryptor()
        stripe_key = encryptor.decrypt(stripe_row[0])
        
        # 3. Create Stripe Checkout Session
        stripe.api_key = stripe_key
        
        # Convert total to cents/pence
        amount_cents = int(float(total) * 100)
        
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'currency_symbol'", (comp_id,))
        curr_row = cur.fetchone()
        currency_sym = curr_row[0] if curr_row else '£'
        currency_code = 'gbp' if currency_sym == '£' else 'usd' # Simplified mapping
        
        # Build success/cancel URLs
        base_url = request.host_url.rstrip('/')
        success_url = f"{base_url}/pay/invoice/{invoice_id}/success?session_id={{CHECKOUT_SESSION_ID}}"
        cancel_url = f"{base_url}/pay/invoice/{invoice_id}/cancel"
        
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            customer_email=client_email,
            line_items=[{
                'price_data': {
                    'currency': currency_code,
                    'product_data': {
                        'name': f"Invoice {ref}",
                        'description': f"Payment for {client_name}",
                    },
                    'unit_amount': amount_cents,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={'invoice_id': invoice_id, 'company_id': comp_id}
        )
        
        return redirect(session.url)
        
    except Exception as e:
        return f"Error processing payment: {e}", 500
    finally:
        conn.close()

@public_bp.route('/pay/invoice/<int:invoice_id>/success')
def pay_invoice_success(invoice_id):
    session_id = request.args.get('session_id')
    if not session_id:
        return "Invalid session.", 400
        
    conn = get_db()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT company_id FROM invoices WHERE id = %s", (invoice_id,))
        comp_row = cur.fetchone()
        if not comp_row:
            return "Invoice not found.", 404
            
        comp_id = comp_row[0]
        
        # Fetch key
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'stripe_secret_key'", (comp_id,))
        stripe_row = cur.fetchone()
        if stripe_row and stripe_row[0]:
            from utils.encryption import get_encryptor
            encryptor = get_encryptor()
            stripe.api_key = encryptor.decrypt(stripe_row[0])
            
            checkout_session = stripe.checkout.Session.retrieve(session_id)
            if checkout_session.payment_status == 'paid':
                cur.execute("UPDATE invoices SET status = 'Paid' WHERE id = %s", (invoice_id,))
                conn.commit()
                return "<h1>Payment Successful!</h1><p>Thank you. Your invoice has been marked as paid.</p>", 200
                
        return "Payment verification failed.", 400
        
    except Exception as e:
        return f"Error: {e}", 500
    finally:
        conn.close()

@public_bp.route('/pay/invoice/<int:invoice_id>/cancel')
def pay_invoice_cancel(invoice_id):
    return "<h1>Payment Cancelled</h1><p>You can try again when you are ready.</p>", 200

from utils.extensions import csrf

@public_bp.route('/webhooks/tenant/stripe', methods=['POST'])
@csrf.exempt
def tenant_stripe_webhook():
    """
    Handles Stripe webhooks for tenant invoices securely without requiring a webhook secret.
    It takes the session ID from the webhook and fetches the actual session from Stripe 
    to verify its authenticity and payment status.
    """
    payload = request.get_json(silent=True)
    if not payload:
        return "No payload", 400
        
    if payload.get('type') == 'checkout.session.completed':
        session_obj = payload.get('data', {}).get('object', {})
        session_id = session_obj.get('id')
        
        metadata = session_obj.get('metadata', {})
        invoice_id = metadata.get('invoice_id')
        comp_id = metadata.get('company_id')
        
        if not invoice_id or not comp_id or not session_id:
            return "Missing metadata", 200
            
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'stripe_secret_key'", (comp_id,))
            row = cur.fetchone()
            if row and row[0]:
                from utils.encryption import get_encryptor
                stripe.api_key = get_encryptor().decrypt(row[0])
                
                # Fetch directly from Stripe to verify authenticity
                verified_session = stripe.checkout.Session.retrieve(session_id)
                if verified_session.payment_status == 'paid':
                    cur.execute("UPDATE invoices SET status = 'Paid' WHERE id = %s AND company_id = %s", (invoice_id, comp_id))
                    conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"Tenant Webhook Error: {e}")
        finally:
            conn.close()
            
    return "OK", 200

@public_bp.route('/set-language/<lang>')
def set_public_language(lang):
    """Sets the public website language in the session and redirects back."""
    from flask import session, redirect, request
    from utils.translations import LANGUAGES
    
    if lang in LANGUAGES:
        session['public_lang'] = lang
        
    # Redirect back to where they came from, or home
    referrer = request.referrer
    if referrer:
        return redirect(referrer)
    return redirect(url_for('public.home'))
