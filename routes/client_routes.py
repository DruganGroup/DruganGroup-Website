from flask import Blueprint, render_template

client_bp = Blueprint('client', __name__)

@client_bp.route('/client-portal')
@client_bp.route('/client-portal.html')
def client_portal_login():
    # Renders the template inside the 'client' folder
    return render_template('client/client_login.html')

@client_bp.route('/track-my-job/<job_id>')
def track_job(job_id):
    # Logic to fetch job details would go here
    return render_template('client/client_tracking.html', job_id=job_id)