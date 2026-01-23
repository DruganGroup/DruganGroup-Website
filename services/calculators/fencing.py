# services/calculators/fencing.py
import math
from .base import BaseCalculator

class FencingCalculator(BaseCalculator):
    def __init__(self):
        self.name = "🚧 Fencing (Closeboard)"
        self.id = "fencing"

    def get_config(self):
        # Defines inputs for Fencing
        return {
            'id': self.id,
            'name': self.name,
            'fields': [
                {'id': 'length', 'label': 'Length (m)', 'type': 'number', 'default': 20, 'placeholder': 'e.g. 20'},
                {'id': 'height', 'label': 'Height (m)', 'type': 'number', 'default': 1.8, 'placeholder': 'e.g. 1.8'}
            ]
        }

    def calculate_requirements(self, inputs):
        # 1. Parse Inputs (with defaults)
        length_m = float(inputs.get('length', 0))
        height_m = float(inputs.get('height', 1.8))
        bay_width = 1.8  # Standard post spacing (meters)
        
        if length_m <= 0:
            return {'materials': [], 'labor_hours': 0, 'waste_load': 0}

        # 2. Logic: Calculate Quantities
        num_bays = math.ceil(length_m / bay_width)
        num_posts = num_bays + 1  # Always 1 more post than bays
        
        # Rails: Usually 2 rails for <1.2m, 3 rails for >1.2m
        rails_per_bay = 3 if height_m > 1.2 else 2
        total_rails = num_bays * rails_per_bay
        
        # Feather Edge Boards (approx 125mm wide with 25mm overlap = 100mm coverage)
        # So 10 boards per meter
        boards_per_meter = 10
        total_boards = math.ceil(length_m * boards_per_meter)
        
        # Gravel Boards (1 per bay)
        total_gravel_boards = num_bays

        # Postcrete (1.5 bags per post is a safe commercial estimate)
        bags_postcrete = math.ceil(num_posts * 1.5)

        # 3. Logic: Calculate Labor
        # Rule of thumb: 1.5 man-hours per bay for dig + set + clad
        hours_per_bay = 1.5
        total_labor_hours = num_bays * hours_per_bay

        # 4. Logic: Waste (Soil displaced by post holes)
        # Approx 0.04 cubic meters per hole -> ~50kg soil
        waste_kg = num_posts * 50 

        # 5. Build The Shopping List
        materials = [
            {'name': f"Fence Post 100x100 ({height_m + 0.6}m)", 'qty': num_posts},
            {'name': "Postcrete (20kg)", 'qty': bags_postcrete},
            {'name': "Cant Rails (3m)", 'qty': total_rails},
            {'name': f"Feather Edge Boards ({height_m}m)", 'qty': total_boards},
            {'name': "Gravel Boards (3m)", 'qty': total_gravel_boards},
            {'name': "Capping Rail (3m)", 'qty': math.ceil(length_m / 3)},
            {'name': "Box of Nails (50mm)", 'qty': 1 if length_m < 20 else 2}
        ]

        return {
            'materials': materials,
            'labor_hours': total_labor_hours,
            'waste_load': waste_kg,
            'summary': f"Fencing: {length_m}m run ({num_bays} bays) at {height_m}m height."
        }