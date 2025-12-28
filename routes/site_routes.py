from flask import Blueprint, render_template

site_bp = Blueprint('site', __name__)

@site_bp.route('/site-companion')
def site_dashboard():
    # This looks for the file in templates/site/site_dashboard.html
    return render_template('site/site_dashboard.html')