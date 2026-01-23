# services/calculators/__init__.py
from .fencing import FencingCalculator
from .roofing import RoofingCalculator

# Register available calculators here
# If you add patio.py later, import it here and add to the dict.
AVAILABLE_CALCS = {
    'fencing': FencingCalculator(),
    'roofing': RoofingCalculator(),
}

def get_calculator(trade_type):
    """
    Factory function to retrieve the correct calculator class.
    """
    return AVAILABLE_CALCS.get(trade_type)