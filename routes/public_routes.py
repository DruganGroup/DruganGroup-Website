from flask import Blueprint, render_template

# Create the Blueprint (this is like a mini-app)
public_bp = Blueprint('public', __name__)

@public_bp.route('/')
@public_bp.route('/index.html')
def home():
    return render_template('public/index.html')

@public_bp.route('/about')
@public_bp.route('/about.html')
def about():
    return render_template('public/about.html')

@public_bp.route('/services')
@public_bp.route('/services.html')
def services():
    return render_template('public/services.html')

@public_bp.route('/tradecore')
@public_bp.route('/tradecore.html')
def tradecore():
    return render_template('public/tradecore.html')

@public_bp.route('/forensics')
@public_bp.route('/forensics.html')
def forensics():
    return render_template('public/forensics.html')

@public_bp.route('/contact')
@public_bp.route('/contact.html')
def contact():
    return render_template('public/contact.html')

@public_bp.route('/pricing')
@public_bp.route('/pricing.html')
def pricing():
    return render_template('public/pricing.html')

@public_bp.route('/legal')
@public_bp.route('/legal.html')
def legal():
    return render_template('public/legal.html')

@public_bp.route('/process')
@public_bp.route('/process.html')
def process():
    return render_template('public/process.html')

# Service Sub-pages
@public_bp.route('/roofing')
@public_bp.route('/roofing.html')
def roofing(): return render_template('public/roofing.html')

@public_bp.route('/groundworks')
@public_bp.route('/groundworks.html')
def groundworks(): return render_template('public/groundworks.html')

@public_bp.route('/landscaping')
@public_bp.route('/landscaping.html')
def landscaping(): return render_template('public/landscaping.html')

@public_bp.route('/maintenance')
@public_bp.route('/maintenance.html')
def maintenance(): return render_template('public/maintenance.html')

@public_bp.route('/management')
@public_bp.route('/management.html')
def management(): return render_template('public/management.html')