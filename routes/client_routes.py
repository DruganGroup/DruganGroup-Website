from flask import Blueprint, render_template

client_bp = Blueprint('client', __name__)

@client_bp.route('/client-portal')
def client_portal_login():
    return render_template('client/client_login.html')