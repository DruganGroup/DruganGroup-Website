class BaseCalculator:
    """
    The blueprint for all trade calculators.
    Every module must implement these methods.
    """
    
    def __init__(self):
        self.name = "Unknown Calculator"
        self.id = "unknown"

    def calculate_requirements(self, inputs):
        """
        Receives user inputs (e.g., length=20m).
        Returns a dictionary containing:
        - 'materials': List of items needed (names and quantities).
        - 'labor_hours': Estimated man-hours to complete.
        - 'waste_load': Estimated waste in kg/bags.
        """
        raise NotImplementedError("Every calculator must implement this method!")