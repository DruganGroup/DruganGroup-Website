import math
from .base import BaseCalculator

class RoofingCalculator(BaseCalculator):
    def __init__(self):
        self.name = "Pitched Roof (Tiling)"
        self.id = "roofing_tiled"

    def calculate_requirements(self, inputs):
        # 1. Parse Inputs
        area_sqm = float(inputs.get('area', 0))
        pitch = inputs.get('pitch', 'standard') # 'standard' or 'steep'
        
        if area_sqm <= 0:
            return {'materials': [], 'labor_hours': 0, 'waste_load': 0}

        # 2. Logic: Quantities
        # Tiles: Standard concrete interlocking tiles approx 10/sqm
        # Steep roofs often require more overlap (11-12/sqm)
        tiles_per_sqm = 12 if pitch == 'steep' else 10
        total_tiles = math.ceil(area_sqm * tiles_per_sqm)
        
        # Batten: Standard 600mm rafter spacing -> approx 3.5m batten per sqm
        total_batten_m = math.ceil(area_sqm * 3.5)
        
        # Membrane: Area + 15% for laps/waste
        total_membrane_sqm = math.ceil(area_sqm * 1.15)
        
        # Nails: Approx 20 nails per sqm (tiles + batten) -> box size logic
        nails_kg = 5 if area_sqm > 50 else 2

        # 3. Logic: Labor
        # Expert roofer: approx 1.5 hours per sqm for felt, batten & tile
        labor_hours = math.ceil(area_sqm * 1.5)

        # 4. Logic: Waste
        # Off-cuts and breakage usually ~5% of material weight
        # 1 sqm tiles ~ 50kg. Total weight = 50 * area. 5% waste.
        waste_kg = (area_sqm * 50) * 0.05

        # 5. Build Shopping List
        materials = [
            {'name': "Roof Tiles (Concrete Interlocking)", 'qty': total_tiles},
            {'name': "Treated Roofing Batten (25x50mm)", 'qty': total_batten_m},
            {'name': "Breathable Membrane (Roll)", 'qty': math.ceil(total_membrane_sqm / 50)}, # 50sqm rolls
            {'name': "Galvanized Nails (65mm)", 'qty': nails_kg},
            {'name': "Eaves Trays (1.5m)", 'qty': math.ceil(math.sqrt(area_sqm))} # Rough est of eaves length
        ]

        return {
            'materials': materials,
            'labor_hours': labor_hours,
            'waste_load': waste_kg,
            'summary': f"Roofing: {area_sqm}m² ({pitch} pitch) - Felt, Batten & Tile."
        }