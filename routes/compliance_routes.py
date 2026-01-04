from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify
from db import get_db
import json
from datetime import date

# Define the new Blueprint
compliance_bp = Blueprint('compliance', __name__)

def check_access():
    if 'user_id' not in session: return False
    return True

# --- API: SAVE EICR (The Brain) ---
@compliance_bp.route('/compliance/eicr/save', methods=['POST'])
def save_eicr():
    if not check_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        # 1. Get the JSON data sent from the JavaScript
        payload = request.json
        comp_id = session.get('company_id')
        
        prop_id = payload.get('prop_id')
        status = payload.get('status', 'Draft') # 'Draft' or 'Issued'
        
        # 2. Extract specific fields for columns, keep the rest in JSON
        # We store the HUGE circuit list inside the 'data' column
        form_data = json.dumps(payload) 
        
        conn = get_db(); cur = conn.cursor()
        
        # 3. Check if we are updating an existing cert or creating a new one
        cert_id = payload.get('cert_id')
        
        if cert_id:
            # UPDATE existing
            cur.execute("""
                UPDATE certificates 
                SET data = %s, status = %s, date_issued = CURRENT_DATE
                WHERE id = %s AND company_id = %s
            """, (form_data, status, cert_id, comp_id))
            msg = "Certificate Updated"
        else:
            # INSERT new
            cur.execute("""
                INSERT INTO certificates (company_id, property_id, type, status, data, engineer_name, date_issued)
                VALUES (%s, %s, 'EICR', %s, %s, %s, CURRENT_DATE)
                RETURNING id
            """, (comp_id, prop_id, status, form_data, session.get('user_name', 'Engineer')))
            cert_id = cur.fetchone()[0]
            msg = "Certificate Created"

        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': msg, 'cert_id': cert_id})

    except Exception as e:
        print(f"EICR Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})