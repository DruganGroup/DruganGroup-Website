from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for
from db import get_db
import json
from datetime import date
from services.pdf_generator import generate_pdf 

compliance_bp = Blueprint('compliance', __name__)

def check_access():
    # Only logged-in users can save certs
    return 'user_id' in session

@compliance_bp.route('/office/compliance')
def compliance_dashboard():
    if 'user_id' not in session: return redirect('/login')
    comp_id = session.get('company_id')
    conn = get_db(); cur = conn.cursor()
    
    # Check for expiring certificates (next 30 days or already expired)
    cur.execute("""
        SELECT p.id, p.address_line1, p.postcode, c.name,
               p.gas_expiry, p.eicr_expiry, p.epc_expiry, p.pat_expiry
        FROM properties p
        LEFT JOIN clients c ON p.client_id = c.id
        WHERE p.company_id = %s
          AND (
               (p.gas_expiry IS NOT NULL AND p.gas_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.eicr_expiry IS NOT NULL AND p.eicr_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.epc_expiry IS NOT NULL AND p.epc_expiry <= CURRENT_DATE + INTERVAL '30 days') OR
               (p.pat_expiry IS NOT NULL AND p.pat_expiry <= CURRENT_DATE + INTERVAL '30 days')
          )
        ORDER BY p.gas_expiry ASC NULLS LAST
    """, (comp_id,))
    
    expiring_props = []
    for row in cur.fetchall():
        expiring_props.append({
            'prop_id': row[0], 'address': f"{row[1]}, {row[2]}", 'client': row[3],
            'gas': row[4], 'eicr': row[5], 'epc': row[6], 'pat': row[7]
        })
        
    # Get config for layout
    cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (comp_id,))
    settings = {r[0]: r[1] for r in cur.fetchall()}
    brand_color = settings.get('brand_color', '#333')
    logo = settings.get('logo', '/static/images/logo.png')
    
    pass
    return render_template('office/compliance_dashboard.html', expiring_props=expiring_props, brand_color=brand_color, logo=logo)

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
            
            # Auto-bill Certificate
            job_id = payload.get('job_id')
            if job_id:
                cur.execute("SELECT value FROM settings WHERE key='fee_eicr_base' AND company_id=%s", (comp_id,))
                base_fee_row = cur.fetchone()
                base_fee = float(base_fee_row[0]) if base_fee_row and base_fee_row[0] else 0.0
                
                cur.execute("SELECT value FROM settings WHERE key='fee_eicr_circuit' AND company_id=%s", (comp_id,))
                circuit_fee_row = cur.fetchone()
                circuit_fee = float(circuit_fee_row[0]) if circuit_fee_row and circuit_fee_row[0] else 0.0
                
                num_circuits = len(payload.get('circuits', []))
                total_fee = base_fee + (num_circuits * circuit_fee)
                
                if total_fee > 0:
                    desc = f"EICR Certificate (Base + {num_circuits} Circuits)"
                    cur.execute("""
                        INSERT INTO job_materials (job_id, description, quantity, unit_price, cost_price, added_at)
                        VALUES (%s, %s, 1, %s, 0.0, NOW())
                    """, (job_id, desc, total_fee))

        conn.commit(); pass
        
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
        
        # Save to job_evidence if job_id is provided
        job_id = data.get('job_id')
        if job_id:
            db_path = f"static/uploads/{filename}"
            cur.execute("""
                INSERT INTO job_evidence (job_id, filepath, uploaded_by, file_type, uploaded_at)
                VALUES (%s, %s, %s, 'CP12', NOW())
            """, (job_id, db_path, session.get('user_id')))
            
            # Auto-bill Certificate
            cur.execute("SELECT value FROM settings WHERE key='fee_cp12' AND company_id=%s", (comp_id,))
            fee_row = cur.fetchone()
            fee = float(fee_row[0]) if fee_row and fee_row[0] else 0.0
            if fee > 0:
                cur.execute("""
                    INSERT INTO job_materials (job_id, description, quantity, unit_price, cost_price, added_at)
                    VALUES (%s, 'Gas Safety Certificate (CP12)', 1, %s, 0.0, NOW())
                """, (job_id, fee))
        
        # 4. THE "ISSUED" LOGIC (Updates Property Table)
        # Gas safety is valid for 1 year
        next_due = data.get('next_date')
        if next_due: 
            cur.execute("UPDATE properties SET gas_expiry = %s WHERE id = %s AND company_id = %s", (next_due, prop_id, comp_id))
            
        conn.commit(); pass
        
        return jsonify({'success': True, 'redirect_url': '/office-hub'})

    except Exception as e:
        print(f"Gas Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})

# --- 3. EPC SAVE LOGIC ---
@compliance_bp.route('/office/cert/epc/save', methods=['POST']) 
def save_epc_cert():
    if not check_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        data = request.json
        prop_id = data.get('prop_id')
        comp_id = session.get('company_id')
        
        conn = get_db(); cur = conn.cursor()

        ref = f"EPC-{prop_id}-{int(date.today().strftime('%s'))}"
        filename = f"{ref}.pdf"
        
        cur.execute("SELECT p.address_line1, p.postcode, c.name, c.email FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (prop_id,))
        p_row = cur.fetchone()
        prop_info = {'address': f"{p_row[0]}, {p_row[1]}", 'client': p_row[2], 'id': prop_id}
        
        pdf_context = {
            'prop': prop_info, 
            'data': data, 
            'signature_url': data.get('signature_img'), 
            'today': date.today().strftime('%d/%m/%Y')
        }
        generate_pdf('office/certs/uk/epc.html', pdf_context, filename)
        
        # Save to job_evidence if job_id is provided
        job_id = data.get('job_id')
        if job_id:
            db_path = f"static/uploads/{filename}"
            cur.execute("""
                INSERT INTO job_evidence (job_id, filepath, uploaded_by, file_type, uploaded_at)
                VALUES (%s, %s, %s, 'EPC', NOW())
            """, (job_id, db_path, session.get('user_id')))
            
            # Auto-bill Certificate
            cur.execute("SELECT value FROM settings WHERE key='fee_epc' AND company_id=%s", (comp_id,))
            fee_row = cur.fetchone()
            fee = float(fee_row[0]) if fee_row and fee_row[0] else 0.0
            if fee > 0:
                cur.execute("""
                    INSERT INTO job_materials (job_id, description, quantity, unit_price, cost_price, added_at)
                    VALUES (%s, 'Energy Performance Certificate (EPC)', 1, %s, 0.0, NOW())
                """, (job_id, fee))
        
        next_due = data.get('next_date')
        if next_due: 
            cur.execute("UPDATE properties SET epc_expiry = %s WHERE id = %s AND company_id = %s", (next_due, prop_id, comp_id))
            
        conn.commit(); pass
        
        return jsonify({'success': True, 'redirect_url': '/office-hub'})

    except Exception as e:
        print(f"EPC Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})

# --- 4. LEGIONELLA SAVE LOGIC ---
@compliance_bp.route('/office/cert/legionella/save', methods=['POST']) 
def save_legionella_cert():
    if not check_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        data = request.json
        prop_id = data.get('prop_id')
        comp_id = session.get('company_id')
        
        conn = get_db(); cur = conn.cursor()

        ref = f"LRA-{prop_id}-{int(date.today().strftime('%s'))}"
        filename = f"{ref}.pdf"
        
        cur.execute("SELECT p.address_line1, p.postcode, c.name, c.email FROM properties p JOIN clients c ON p.client_id = c.id WHERE p.id = %s", (prop_id,))
        p_row = cur.fetchone()
        prop_info = {'address': f"{p_row[0]}, {p_row[1]}", 'client': p_row[2], 'id': prop_id}
        
        pdf_context = {
            'prop': prop_info, 
            'data': data, 
            'signature_url': data.get('signature_img'), 
            'today': date.today().strftime('%d/%m/%Y')
        }
        generate_pdf('office/certs/uk/legionella.html', pdf_context, filename)
        
        # Save to job_evidence if job_id is provided
        job_id = data.get('job_id')
        if job_id:
            db_path = f"static/uploads/{filename}"
            cur.execute("""
                INSERT INTO job_evidence (job_id, filepath, uploaded_by, file_type, uploaded_at)
                VALUES (%s, %s, %s, 'Legionella Risk', NOW())
            """, (job_id, db_path, session.get('user_id')))
            
            # Auto-bill Certificate
            cur.execute("SELECT value FROM settings WHERE key='fee_legionella' AND company_id=%s", (comp_id,))
            fee_row = cur.fetchone()
            fee = float(fee_row[0]) if fee_row and fee_row[0] else 0.0
            if fee > 0:
                cur.execute("""
                    INSERT INTO job_materials (job_id, description, quantity, unit_price, cost_price, added_at)
                    VALUES (%s, 'Legionella Risk Assessment', 1, %s, 0.0, NOW())
                """, (job_id, fee))
        
        # We don't have a specific legionella column, but we can reuse PAT or add a new one if available.
        # Let's see if there is one. We'll skip updating property table for now or we could add a new column later.
            
        conn.commit(); pass
        
        return jsonify({'success': True, 'redirect_url': '/office-hub'})

    except Exception as e:
        print(f"Legionella Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@compliance_bp.route('/office/cert/<country_code>/<cert_type>/save', methods=['POST'])
def save_generic_cert(country_code, cert_type):
    if not check_access(): return jsonify({'success': False, 'error': 'Unauthorized'}), 403
    
    try:
        data = request.json
        prop_id = data.get('prop_id')
        comp_id = session.get('company_id')
        
        conn = get_db(); cur = conn.cursor()

        # 1. Generate Filename Reference
        cert_type_upper = cert_type.upper()
        # For simplicity, using timestamp as unique id since strftime('%s') isn't standard on Windows
        import time
        ref = f"{cert_type_upper}-{prop_id}-{int(time.time())}"
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
        
        country_code = country_code.lower()
        generate_pdf(f'office/certs/{country_code}/{cert_type}.html', pdf_context, filename)
        
        # Save to job_evidence if job_id is provided
        job_id = data.get('job_id')
        if job_id:
            db_path = f"static/uploads/{filename}"
            cur.execute("""
                INSERT INTO job_evidence (job_id, filepath, uploaded_by, file_type, uploaded_at)
                VALUES (%s, %s, %s, %s, NOW())
            """, (job_id, db_path, session.get('user_id'), cert_type_upper))

        # 4. Link to CP12 (Gas) or EICR (Electrical) logic
        next_due = data.get('next_date')
        if next_due:
            gas_equivalents = ['gas_cert', 'qualigaz', 'gas_dvgw', 'epa_energy']
            electrical_equivalents = ['nfpa70e', 'esa_defect', 'ccew', 'cie_elec', 'consuel', 'dguv_v3', 'dewa_elec']
            
            if cert_type.lower() in gas_equivalents:
                cur.execute("UPDATE properties SET gas_expiry = %s WHERE id = %s AND company_id = %s", (next_due, prop_id, comp_id))
            elif cert_type.lower() in electrical_equivalents:
                cur.execute("UPDATE properties SET eicr_expiry = %s WHERE id = %s AND company_id = %s", (next_due, prop_id, comp_id))

        conn.commit(); pass
        
        return jsonify({'success': True, 'redirect_url': '/office-hub'})

    except Exception as e:
        print(f"Generic Cert Save Error: {e}")
        return jsonify({'success': False, 'error': str(e)})