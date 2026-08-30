def calculate_vehicle_daily_cost(cur, vehicle_id, base_cost, driver_id):
    """
    Calculates the 'True Gang Cost' by summing the base vehicle cost 
    with the calculated daily rate of its driver and crew members.
    """
    daily_total = float(base_cost or 0)
    
    # A. Add Driver Cost
    if driver_id:
        cur.execute("SELECT pay_rate, pay_model FROM staff WHERE id = %s", (driver_id,))
        d_row = cur.fetchone()
        if d_row:
            rate, model_type = float(d_row[0] or 0), d_row[1]
            if model_type == 'Hour': daily_total += (rate * 8)
            elif model_type == 'Day': daily_total += rate
            elif model_type == 'Year': daily_total += (rate / 260)

    # B. Add Crew Cost
    if vehicle_id:
        cur.execute("""
            SELECT s.pay_rate, s.pay_model FROM vehicle_crews vc
            JOIN staff s ON vc.staff_id = s.id
            WHERE vc.vehicle_id = %s
        """, (vehicle_id,))
        for c_row in cur.fetchall():
            rate, model_type = float(c_row[0] or 0), c_row[1]
            if model_type == 'Hour': daily_total += (rate * 8)
            elif model_type == 'Day': daily_total += rate
            elif model_type == 'Year': daily_total += (rate / 260)
        
    return daily_total

def get_company_markups(cur, comp_id):
    """
    Returns (labour_markup_percent, material_markup_percent) from settings.
    Defaults to (20.0, 20.0) if not configured.
    """
    cur.execute("""
        SELECT key, value FROM settings 
        WHERE company_id = %s AND key IN ('labour_markup_percent', 'material_markup_percent')
    """, (comp_id,))
    settings = {r[0]: r[1] for r in cur.fetchall()}
    labour_markup = float(settings.get('labour_markup_percent') or 20.0)
    material_markup = float(settings.get('material_markup_percent') or 20.0)
    return labour_markup, material_markup

def get_effective_vehicle_gang_cost(cur, comp_id, vehicle_id=None, engineer_id=None):
    """
    Finds the active vehicle and returns (vehicle_id, vehicle_reg, daily_gang_cost).
    """
    if vehicle_id:
        cur.execute("SELECT id, reg_plate, daily_cost, assigned_driver_id FROM vehicles WHERE id = %s AND company_id = %s", (vehicle_id, comp_id))
        v_row = cur.fetchone()
        if v_row:
            gang_cost = calculate_vehicle_daily_cost(cur, v_row[0], v_row[2], v_row[3] or engineer_id)
            return v_row[0], v_row[1] or "Fleet Vehicle", gang_cost

    if engineer_id:
        cur.execute("SELECT id, reg_plate, daily_cost, assigned_driver_id FROM vehicles WHERE assigned_driver_id = %s AND company_id = %s LIMIT 1", (engineer_id, comp_id))
        v_row = cur.fetchone()
        if v_row:
            gang_cost = calculate_vehicle_daily_cost(cur, v_row[0], v_row[2], engineer_id)
            return v_row[0], v_row[1] or "Assigned Vehicle", gang_cost

    cur.execute("SELECT id, reg_plate, daily_cost, assigned_driver_id FROM vehicles WHERE company_id = %s AND status = 'Active' LIMIT 1", (comp_id,))
    v_row = cur.fetchone()
    if v_row:
        gang_cost = calculate_vehicle_daily_cost(cur, v_row[0], v_row[2], v_row[3])
        return v_row[0], v_row[1] or "Company Van", gang_cost

    return None, "No Vehicle", 0.0
def get_effective_vehicle_running_cost(cur, comp_id, vehicle_id=None, engineer_id=None):
    """
    Finds the active vehicle and returns (vehicle_id, vehicle_reg, daily_base_running_cost).
    Does NOT include driver or crew wages (used when labour is already billed via timesheets).
    """
    if vehicle_id:
        cur.execute("SELECT id, reg_plate, daily_cost FROM vehicles WHERE id = %s AND company_id = %s", (vehicle_id, comp_id))
        v_row = cur.fetchone()
        if v_row:
            return v_row[0], v_row[1] or "Fleet Vehicle", float(v_row[2] or 0)

    if engineer_id:
        cur.execute("SELECT id, reg_plate, daily_cost FROM vehicles WHERE assigned_driver_id = %s AND company_id = %s LIMIT 1", (engineer_id, comp_id))
        v_row = cur.fetchone()
        if v_row:
            return v_row[0], v_row[1] or "Assigned Vehicle", float(v_row[2] or 0)

    cur.execute("SELECT id, reg_plate, daily_cost FROM vehicles WHERE company_id = %s AND status = 'Active' LIMIT 1", (comp_id,))
    v_row = cur.fetchone()
    if v_row:
        return v_row[0], v_row[1] or "Company Van", float(v_row[2] or 0)

    return None, "No Vehicle", 0.0

def calculate_service_request_estimate(cur, comp_id, issue_desc="", property_id=None, cert_type=None):
    """
    Calculates a cross-referenced estimated budget and price based on:
    - Certificate standard pricing (if CP12, EICR, EPC, Legionella)
    - Average labour rate × estimated hours + labour markup
    - Average van/gang daily or half-day rate + markup
    - Materials baseline allowance + material markup
    """
    labour_markup, material_markup = get_company_markups(cur, comp_id)
    desc_lower = (issue_desc or "").lower()

    cert_fees = {
        'cp12': 85.0,
        'gas': 85.0,
        'eicr': 180.0,
        'electrical': 180.0,
        'epc': 75.0,
        'legionella': 75.0,
        'boiler': 95.0
    }

    matched_cert = cert_type.lower() if cert_type else None
    if not matched_cert:
        for k in cert_fees:
            if k in desc_lower:
                matched_cert = k
                break

    if matched_cert:
        base_fee = cert_fees.get(matched_cert, 85.0)
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = %s", (comp_id, f"cert_price_{matched_cert}"))
        row = cur.fetchone()
        if row and row[0]:
            try: base_fee = float(row[0])
            except: pass
        
        return {
            'is_certificate': True,
            'cert_type': matched_cert.upper(),
            'estimated_cost': round(base_fee * 0.65, 2),
            'estimated_price': round(base_fee, 2),
            'estimated_hours': 1.5,
            'description': f"Compliance / Certificate ({matched_cert.upper()})"
        }

    est_hours = 2.0
    cur.execute("SELECT AVG(pay_rate) FROM staff WHERE company_id = %s AND pay_model = 'Hour' AND status = 'Active'", (comp_id,))
    avg_rate_row = cur.fetchone()
    avg_hourly_wage = float(avg_rate_row[0]) if (avg_rate_row and avg_rate_row[0]) else 25.0

    labour_cost = est_hours * avg_hourly_wage
    labour_billable = labour_cost * (1 + (labour_markup / 100.0))

    _, _, daily_gang_cost = get_effective_vehicle_gang_cost(cur, comp_id)
    van_cost_portion = (daily_gang_cost / 4.0) if daily_gang_cost > 0 else 15.0
    van_billable = van_cost_portion * (1 + (labour_markup / 100.0))

    materials_cost_est = 25.0
    materials_billable = materials_cost_est * (1 + (material_markup / 100.0))

    total_cost = labour_cost + van_cost_portion + materials_cost_est
    total_price = labour_billable + van_billable + materials_billable

    return {
        'is_certificate': False,
        'cert_type': None,
        'estimated_cost': round(total_cost, 2),
        'estimated_price': round(total_price, 2),
        'estimated_hours': est_hours,
        'labour_billable': round(labour_billable, 2),
        'van_billable': round(van_billable, 2),
        'materials_billable': round(materials_billable, 2),
        'description': "Fault Diagnostic & Callout Repair"
    }

