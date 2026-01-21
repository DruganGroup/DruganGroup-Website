from db import get_db

class PricingEngine:
    
    @staticmethod
    def calculate_job_cost(company_id, requirements, resources):
        conn = get_db()
        cur = conn.cursor()
        
        # 1. GET SETTINGS
        cur.execute("SELECT key, value FROM settings WHERE company_id = %s", (company_id,))
        settings = {row[0]: row[1] for row in cur.fetchall()}
        
        mat_markup = float(settings.get('material_markup_percent', 0)) / 100
        lab_markup = float(settings.get('labour_markup_percent', 0)) / 100
        
        # 2. CALCULATE MATERIALS
        total_material_cost = 0.0
        priced_materials = [] # Detailed list for the "Material File"
        shopping_list_by_supplier = {} 

        for item in requirements.get('materials', []):
            item_name = item['name']
            qty = item['qty']
            
            # Lookup Logic (Simplified for brevity - same as before)
            cur.execute("""
                SELECT m.cost_price, s.name, s.email FROM materials m
                LEFT JOIN suppliers s ON m.supplier_id = s.id
                WHERE m.company_id = %s AND LOWER(m.name) = LOWER(%s)
            """, (company_id, item_name))
            match = cur.fetchone()
            
            cost_price = float(match[0]) if match else 0.0
            supplier_name = match[1] if match else "Generic"
            
            # Calculate Sell Price
            sell_price = cost_price * (1 + mat_markup)
            line_total = sell_price * qty
            total_material_cost += line_total
            
            # Add to Detailed List
            priced_materials.append({
                'desc': item_name, 'qty': qty, 
                'cost': sell_price, 'total': line_total, 'supplier': supplier_name
            })
            
            # (Shopping list logic remains same)

        # 3. CALCULATE RESOURCES (LABOUR)
        total_resource_cost = 0.0
        needed_hours = requirements.get('labor_hours', 0)
        
        # Calculate Fleet Hourly Rate (same as before)
        fleet_cost_per_hour = 0.0
        num_staff = 0
        for vehicle in resources:
            fleet_cost_per_hour += (vehicle.get('daily_cost', 0) / 8)
            fleet_cost_per_hour += (vehicle.get('driver_rate', 0) * (1 + lab_markup))
            num_staff += 1
            for crew in vehicle.get('crew', []):
                fleet_cost_per_hour += (crew.get('rate', 0) * (1 + lab_markup))
                num_staff += 1

        if num_staff > 0:
            total_resource_cost = fleet_cost_per_hour * (needed_hours / num_staff)
            est_days = round((needed_hours / num_staff) / 8, 1)
        else:
            est_days = 0

        # 4. CALCULATE WASTE (New!)
        total_waste_cost = 0.0
        waste_kg = requirements.get('waste_load', 0)
        if waste_kg > 0:
            # Simple Logic: £250 per 1000kg (Grab Lorry) or specific logic
            # You can add 'waste_cost_per_ton' to your settings table later
            waste_rate_per_kg = 0.25 
            total_waste_cost = waste_kg * waste_rate_per_kg

        conn.close()

        # 5. CREATE THE "CLEAN QUOTE" SUMMARY
        # This is what gets sent to the Quote Page
        quote_summary_rows = [
            {'desc': "Supply of Materials", 'qty': 1, 'cost': total_material_cost},
            {'desc': "Installation Labour & Plant", 'qty': 1, 'cost': total_resource_cost}
        ]
        if total_waste_cost > 0:
            quote_summary_rows.append({'desc': "Waste Removal & Disposal", 'qty': 1, 'cost': total_waste_cost})

        return {
            'grand_total': total_material_cost + total_resource_cost + total_waste_cost,
            'summary': requirements.get('summary', 'Estimate'),
            'est_duration_days': est_days,
            
            # THE TWO LISTS:
            'quote_rows': quote_summary_rows,       # <--- For the Client Quote
            'detailed_breakdown': priced_materials, # <--- For the Material File
            'shopping_list': shopping_list_by_supplier
        }