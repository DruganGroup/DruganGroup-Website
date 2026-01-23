class BaseCalculator:
    """
    The blueprint for all trade calculators.
    Every module must implement these methods.
    """
    
    def __init__(self):
        self.name = "Unknown Calculator"
        self.id = "unknown"

    def get_config(self):
        """
        Returns the 'Schema' for the frontend to build the form.
        Expected return format:
        {
            'id': self.id,
            'name': self.name,
            'fields': [
                {'id': 'length', 'label': 'Length (m)', 'type': 'number', 'default': 0},
                ...
            ]
        }
        """
        raise NotImplementedError("Every calculator must implement get_config()!")

    def calculate_requirements(self, inputs):
        """
        Receives user inputs (e.g., length=20m).
        Returns a dictionary containing:
        - 'materials': List of items needed (names and quantities).
        - 'labor_hours': Estimated man-hours to complete.
        - 'waste_load': Estimated waste in kg/bags.
        """
        raise NotImplementedError("Every calculator must implement this method!")