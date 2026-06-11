# utils/certificates.py

# A registry mapping country codes to their legally required/industry standard certificates
CERTIFICATE_REGISTRY = {
    'UK': [
        {'id': 'cp12', 'name': 'CP12 (Gas Safety)', 'desc': 'UK Gas Safety Record'},
        {'id': 'eicr', 'name': 'EICR (Electrical)', 'desc': 'Electrical Installation Condition Report'},
        {'id': 'epc', 'name': 'EPC (Energy)', 'desc': 'Energy Performance Certificate'},
        {'id': 'legionella', 'name': 'Legionella Risk', 'desc': 'Legionella Risk Assessment'}
    ],
    'US': [
        {'id': 'nfpa70e', 'name': 'NFPA 70E (Electrical)', 'desc': 'Electrical Safety Assessment'},
        {'id': 'osha', 'name': 'OSHA Hazard Assessment', 'desc': 'General Workplace Safety Form'},
        {'id': 'epa_energy', 'name': 'EPA Energy Audit', 'desc': 'Energy Efficiency Assessment'}
    ],
    'AUS': [
        {'id': 'ccew', 'name': 'CCEW (Electrical)', 'desc': 'Certificate of Compliance for Electrical Work'},
        {'id': 'plumbing_coc', 'name': 'Plumbing CoC', 'desc': 'Plumbing Certificate of Compliance'}
    ]
}

def get_certificates_for_country(country_code):
    """
    Returns the list of certificates applicable to a given country code.
    Defaults to UK if country code is not explicitly supported yet.
    """
    # Normalize country code map
    mapping = {
        'United Kingdom': 'UK',
        'UK': 'UK',
        'United States': 'US',
        'US': 'US',
        'Australia': 'AUS',
        'AUS': 'AUS'
    }
    
    normalized_code = mapping.get(country_code, 'UK')
    return CERTIFICATE_REGISTRY.get(normalized_code, CERTIFICATE_REGISTRY['UK'])
