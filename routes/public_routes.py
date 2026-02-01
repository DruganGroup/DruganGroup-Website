from flask import Blueprint, render_template, request
from db import get_db

# Create the Blueprint
public_bp = Blueprint('public', __name__)

# --- CONFIGURATION ---
DOMAIN_SOFTWARE = 'businessbetter.co.uk'

# --- MAIN PAGES ---
@public_bp.route('/')
@public_bp.route('/index')
@public_bp.route('/index.html')
def home():
    host = request.host.lower()

    # 1. WHITE LABEL CHECK (Direct Logic)
    # Check if we are on a specific company subdomain (e.g. testace.businessbetter...)
    # We filter out 'www', 'localhost', and the main domain itself.
    if 'businessbetter.co.uk' in host and host != 'businessbetter.co.uk' and not host.startswith('www.'):
        subdomain = host.split('.')[0]
        
        conn = get_db()
        cur = conn.cursor()
        
        # Check BOTH 'sub_domain' (new) and 'subdomain' (legacy) columns
        cur.execute("""
            SELECT id, name, value 
            FROM companies c 
            LEFT JOIN settings s ON c.id = s.company_id AND s.key = 'brand_color' 
            WHERE c.subdomain = %s OR c.sub_domain = %s
        """, (subdomain, subdomain))
        data = cur.fetchone()
        
        # Fetch Logo if company exists
        logo_url = None
        if data:
            cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'logo'", (data[0],))
            logo_row = cur.fetchone()
            if logo_row: logo_url = logo_row[0]
        
        conn.close()

        if data:
            # SUCCESS: Render the Client Login from the PORTAL folder
            # We pass the company branding so it looks like "Test Ace"
            return render_template('portal/client_login.html',
                                   company_id=data[0],
                                   company_name=data[1],
                                   brand_color=data[2] or '#c5a059',
                                   logo_url=logo_url)

    # 2. DEFAULT: SHOW MARKETING SITE
    if 'businessbetter.co.uk' in host:
        return render_template('publicbb/index.html')
    else:
        return render_template('public/index.html')

@public_bp.route('/about')
@public_bp.route('/about.html')
def about():
    host = request.host.lower()
    
    if DOMAIN_SOFTWARE in host:
        return render_template('publicbb/about.html')
    else:
        return render_template('public/about.html')

@public_bp.route('/contact')
@public_bp.route('/contact.html')
def contact():
    host = request.host.lower()

    if DOMAIN_SOFTWARE in host:
        # Points to Business Better contact page
        return render_template('publicbb/contact.html') 
    else:
        # Points to Drugan Group contact page
        return render_template('public/contact.html')

@public_bp.route('/pricing')
def pricing():
    host = request.host.lower()
    if DOMAIN_SOFTWARE in host:
        return render_template('publicbb/pricing.html')
    else:
        return render_template('public/index.html')

# --- FEATURES / SALES FUNNEL ROUTES ---

# 1. The Gateway (Who are you?)
@public_bp.route('/features')
def features():
    host = request.host.lower()
    if DOMAIN_SOFTWARE in host:
        return render_template('publicbb/features.html')
    else:
        return render_template('public/index.html')

# 2. For Tradesmen (Winning contracts)
@public_bp.route('/features/trade')
def features_trade():
    host = request.host.lower()
    if DOMAIN_SOFTWARE in host:
        return render_template('publicbb/features_trade.html')
    else:
        return render_template('public/index.html')

# 3. For Estate Agents (Service Desk)
@public_bp.route('/features/agents')
def features_agents():
    host = request.host.lower()
    if DOMAIN_SOFTWARE in host:
        return render_template('publicbb/features_agents.html')
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
    if DOMAIN_SOFTWARE in host:
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
    if DOMAIN_SOFTWARE in host:
        return render_template('publicbb/help.html')
    else:
        # If trade site users need help, maybe redirect to contact or a different page
        return render_template('public/contact.html')