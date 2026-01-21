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
        
        # 2. CALCULATE MATERIALS (Smart Lookup)
        total_material_cost = 0.0
        priced_materials = []
        shopping_list_by_supplier = {} 

        for item in requirements.get('materials', []):
            item_name = item['name']
            qty = item['qty']
            
            # LOOKUP: Find this item in our DB
            cur.execute("""
                SELECT m.cost_price, s.name, s.email 
                FROM materials m
                LEFT JOIN suppliers s ON m.supplier_id = s.id
                WHERE m.company_id = %s AND LOWER(m.name) = LOWER(%s)
            """, (company_id, item_name))
            
            match = cur.fetchone()
            
            if match:
                cost_price = float(match[0])
                supplier_name = match[1] or "Generic Supplier"
                supplier_email = match[2]
            else:
                cost_price = 0.0
                supplier_name = "To Be Sourced"
                supplier_email = None

            # Apply Markup
            sell_price = cost_price * (1 + mat_markup)
            line_total = sell_price * qty
            total_material_cost += line_total
            
            # Add to Quote Data
            priced_materials.append({
                'desc': item_name,
                'qty': qty,
                'cost': sell_price,
                'total': line_total,
                'supplier': supplier_name 
            })

            # Add to Supplier Order List (For One-Click Ordering)
            if supplier_email:
                if supplier_name not in shopping_list_by_supplier:
                    shopping_list_by_supplier[supplier_name] = {
                        'email': supplier_email, 
                        'items': []
                    }
                shopping_list_by_supplier[supplier_name]['items'].append({
                    'name': item_name,
                    'qty': qty
                })

        # 3. CALCULATE RESOURCES (Vehicles + Drivers + Crew)
        total_resource_cost = 0.0
        needed_hours = requirements.get('labor_hours', 0)
        
        fleet_cost_per_hour = 0.0
        num_staff = 0
        
        for vehicle in resources:
            # Vehicle Base Cost
            veh_daily = vehicle.get('daily_cost', 0)
            fleet_cost_per_hour += (veh_daily / 8)
            
            # Driver Cost
            driver_rate = vehicle.get('driver_rate', 0)
            fleet_cost_per_hour += (driver_rate * (1 + lab_markup))
            num_staff += 1
            
            # Crew Costs
            for crew_member in vehicle.get('crew', []):
                rate = crew_member.get('rate', 0)
                fleet_cost_per_hour += (rate * (1 + lab_markup))
                num_staff += 1
        
        if num_staff > 0:
            actual_duration_hours = needed_hours / num_staff
            total_resource_cost = fleet_cost_per_hour * actual_duration_hours
        else:
            actual_duration_hours = 0
            
        conn.close()

        return {
            'materials_total': total_material_cost,
            'resource_total': total_resource_cost,
            'grand_total': total_material_cost + total_resource_cost,
            'breakdown': priced_materials,
            'shopping_list': shopping_list_by_supplier, # <--- Ready for Emailing
            'est_duration_days': round(actual_duration_hours / 8, 1)
        }