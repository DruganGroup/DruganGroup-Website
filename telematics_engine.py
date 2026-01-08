import requests

# --- telematics_engine.py ---
# This file handles the "Translation" between your app and the trackers.

class TelematicsBase:
    """The template that all trackers must follow"""
    def __init__(self, api_key):
        self.api_key = api_key

    def get_stats(self, device_id):
        """Must return a dictionary with: lat, lon, speed, fuel_level"""
        raise NotImplementedError("Must implement get_stats")

# --- Adapter for SAMSARA ---
class SamsaraAdapter(TelematicsBase):
    def get_stats(self, device_id):
        # 1. Build the specific URL for Samsara
        url = f"https://api.samsara.com/fleet/vehicles/{device_id}/stats"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        
        try:
            # 2. Make the request (Timeout prevents hanging if API is down)
            # response = requests.get(url, headers=headers, timeout=5).json()
            
            # NOTE: Since we don't have a real key yet, here is dummy data 
            # so your code works immediately for testing:
            return {
                "lat": 51.5074,     # London
                "lon": -0.1278,
                "speed": 45,
                "fuel_level": 78,
                "status": "Active"
            }
        except Exception as e:
            print(f"Samsara Error: {e}")
            return None

# --- Adapter for GEOTAB ---
class GeotabAdapter(TelematicsBase):
    def get_stats(self, device_id):
        # Placeholder for Geotab logic
        return None

# --- THE MAIN FUNCTION (Import this in your app) ---
def get_tracker_data(provider_name, api_key, device_id):
    """
    Factory function: Looks at the provider name and picks the right tool.
    """
    if not provider_name or not api_key:
        return None
        
    provider = provider_name.lower()
    
    if provider == 'samsara':
        adapter = SamsaraAdapter(api_key)
    elif provider == 'geotab':
        adapter = GeotabAdapter(api_key)
    else:
        return None
    
    return adapter.get_stats(device_id)