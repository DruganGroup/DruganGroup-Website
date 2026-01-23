
from .fencing import FencingCalculator
from .roofing import RoofingCalculator


AVAILABLE_CALCS = {
    'fencing': FencingCalculator(),
    'roofing': RoofingCalculator(),
}

def get_calculator(trade_type):
    """
    Factory: Returns the specific calculator class instance 
    based on the trade_type string.
    """
    return AVAILABLE_CALCS.get(trade_type)