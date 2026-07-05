def calculate_vehicle_daily_cost(cur, vehicle_id, base_cost, driver_id):
    """
    Calculates the 'True Gang Cost' by summing the base vehicle cost 
    with the calculated daily rate of its driver and crew members.
    
    Args:
        cur: Database cursor
        vehicle_id: ID of the vehicle
        base_cost: Base daily cost of the vehicle itself
        driver_id: ID of the assigned driver
        
    Returns:
        float: Total daily cost (Gang Cost)
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
