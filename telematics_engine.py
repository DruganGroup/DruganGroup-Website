import requests
import random
import time

# --- TELEMATICS ENGINE (WHITE LABEL READY) ---
# This engine is 'Stateless'. It accepts an API Key dynamically 
# for each request, ensuring total separation between companies.

class TelematicsBase:
    def get_stats(self, identifier):
        raise NotImplementedError("Must implement get_stats")

# --- 1. SAMSARA ADAPTER ---
class SamsaraAdapter(TelematicsBase):
    def __init__(self, api_key):
        self.api_key = api_key 

    def get_stats(self, url_or_id):
        if not self.api_key:
            return None # Cannot connect without a company key
            
        # Extract ID (e.g. from "https://api.samsara.com/.../12345" -> "12345")
        device_id = str(url_or_id).split('/')[-1] if '/' in str(url_or_id) else str(url_or_id)
        
        # Real Endpoint (Example)
        url = f"https://api.samsara.com/fleet/vehicles/{device_id}/stats"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        try:
            # --- REAL API CALL (Enable when you have a key) ---
            # response = requests.get(url, headers=headers, timeout=5)
            # if response.status_code == 200:
            #     data = response.json()
            #     return {
            #         "lat": data.get('gps', {}).get('latitude'),
            #         "lon": data.get('gps', {}).get('longitude'),
            #         "speed": data.get('gps', {}).get('speedMilesPerHour'),
            #         "fuel_level": data.get('fuelLevel', {}).get('percent'),
            #         "status": "Active",
            #         "provider": "Samsara"
            #     }
            
            # --- SIMULATION (For Testing) ---
            # Returns dummy data so the map works immediately
            return {
                "lat": 51.5074 + (random.uniform(-0.01, 0.01)), 
                "lon": -0.1278 + (random.uniform(-0.01, 0.01)),
                "speed": 45,
                "fuel_level": 78,
                "status": "Active",
                "provider": "Samsara (Sim)"
            }
        except Exception as e:
            print(f"Samsara API Error: {e}")
            return None

# --- 2. SIMULATION ADAPTER ---
class SimulationAdapter(TelematicsBase):
    def get_stats(self, seed):
        base_lat = 54.5; base_lon = -3.0
        return {
            "lat": base_lat + (random.uniform(-1.5, 1.5)),
            "lon": base_lon + (random.uniform(-1.5, 1.5)),
            "speed": random.randint(0, 70),
            "fuel_level": random.randint(20, 100),
            "status": "Moving",
            "provider": "Simulation"
        }

# --- FACTORY FUNCTION ---
def get_tracker_data(tracker_input, api_key=None):
    """
    Decides which tracker to use based on the input URL/ID.
    Requires 'api_key' to be passed in from the database.
    """
    if not tracker_input: return None

    input_lower = str(tracker_input).lower()

    # 1. Check for Advanced Providers
    if "samsara" in input_lower:
        adapter = SamsaraAdapter(api_key)
        return adapter.get_stats(tracker_input)
        
    elif "geotab" in input_lower:
        # Placeholder for Geotab
        return None 

    # 2. Fallback to Simulation (No Key Needed)
    else:
        adapter = SimulationAdapter()
        return adapter.get_stats(tracker_input)