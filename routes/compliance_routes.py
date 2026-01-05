from flask import Blueprint, request, jsonify, session
from db import get_db
import json
from datetime import date
from services.pdf_generator import generate_pdf 

compliance_bp = Blueprint('compliance', __name__)

def check_access():
    # Only logged-in users can save certs
    return 'user_id' in session

# --- 1. EICR (ELECTRICAL) SAVE LOGIC ---
@compliance_bp.route('/compliance/eicr/save', methods=['POST'])
def save_eicr():
    if not check_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        payload = request.json
        comp_id = session.get('company_id')
        prop_id = payload.get('prop_id')
        status = payload.get('status', 'Draft')
        
        # Dump the complex JS object (Circuits + Observations) into JSON string
        form_data = json.dumps(payload)
        
        cert_id = payload.get('cert_id')
        conn = get_db(); cur = conn.cursor()
        
        # A. Save to Certificate Table
        if cert_id:
            cur.execute("""
                UPDATE certificates 
                SET data=%s, status=%s, date_issued=CURRENT_DATE 
                WHERE id=%s AND company_id=%s
            """, (form_data, status, cert_id, comp_id))
            msg = "Certificate Updated"
        else:
            cur.execute("""
                INSERT INTO certificates (company_id, property_id, type, status, data, engineer_name, date_issued) 
                VALUES (%s, %s, 'EICR', %s, %s, %s, CURRENT_DATE) 
                RETURNING id
            """, (comp_id, prop_id, status, form_data, session.get('user_name', 'Engineer')))
            cert_id = cur.fetchone()[0]
            msg = "Certificate Created"

        # B. THE "ISSUED" LOGIC (Updates Property Table)
        if status == 'Issued':
            next_date = payload.get('next_date')
            if next_date: 
                cur.execute("UPDATE properties SET eicr_expiry = %s WHERE id = %s AND company_id = %s", (next_date, prop_id, comp_id))

        conn.commit(); conn.close()
        
        return jsonify({'success': True, 'message': msg, 'cert_id': cert_id})

    except Exception as e:
        print(f"EICR Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})

# --- 2. CP12 (GAS) SAVE LOGIC ---
# Moved here from Office Routes to keep all "Saving" logic in one place
@compliance_bp.route('/office/cert/gas/save', methods=['POST']) 
def save_gas_cert():
    if not check_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        data = request.json
        prop_id = data.get('prop_id')
        comp_id = session.get('company_id')
        
        conn = get_db(); cur = conn.cursor()

        # 1. Generate Filename Reference
        ref = f"CP12-{prop_id}-{int(date.today().strftime('%s'))}"
        filename = f"{ref}.pdf"
        
        # 2. Get Data for PDF Generation
        cur.execute("SELECT p.address_line1, p.postcode, c.name, c.email FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (prop_id,))
        p_row = cur.fetchone()
        prop_info = {'address': f"{p_row[0]}, {p_row[1]}", 'client': p_row[2], 'id': prop_id}
        
        # 3. Generate PDF
        pdf_context = {
            'prop': prop_info, 
            'data': data, 
            'signature_url': data.get('signature_img'), 
            'today': date.today().strftime('%d/%m/%Y')
        }
        # Note: This calls your PDF service
        generate_pdf('office/certs/uk/cp12.html', pdf_context, filename)
        
        # 4. THE "ISSUED" LOGIC (Updates Property Table)
        # Gas safety is valid for 1 year
        next_due = data.get('next_date')
        if next_due: 
            cur.execute("UPDATE properties SET gas_expiry = %s WHERE id = %s AND company_id = %s", (next_due, prop_id, comp_id))
            
        conn.commit(); conn.close()
        
        return jsonify({'success': True, 'redirect_url': '/office-hub'})

    except Exception as e:
        print(f"Gas Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})