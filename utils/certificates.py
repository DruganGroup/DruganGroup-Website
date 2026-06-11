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
    'CAN': [
        {'id': 'esa_defect', 'name': 'ESA Defect Form', 'desc': 'Electrical Safety Authority Defect Form'}
    ],
    'AUS': [
        {'id': 'ccew', 'name': 'CCEW (Electrical)', 'desc': 'Certificate of Compliance for Electrical Work'},
        {'id': 'plumbing_coc', 'name': 'Plumbing CoC', 'desc': 'Plumbing Certificate of Compliance'},
        {'id': 'swms', 'name': 'SWMS (Safety)', 'desc': 'Safe Work Method Statement'}
    ],
    'ES': [
        {'id': 'cie_elec', 'name': 'Boletín Eléctrico (CIE)', 'desc': 'Certificado de Instalación Eléctrica'},
        {'id': 'gas_cert', 'name': 'Boletín de Gas', 'desc': 'Certificado de Instalación de Gas'}
    ],
    'FR': [
        {'id': 'consuel', 'name': 'Attestation Consuel', 'desc': 'Electrical Compliance Certificate'},
        {'id': 'qualigaz', 'name': 'Certificat Qualigaz', 'desc': 'Gas Installation Compliance'}
    ],
    'DE': [
        {'id': 'dguv_v3', 'name': 'DGUV V3 Prüfprotokoll', 'desc': 'Electrical Equipment Testing Protocol'},
        {'id': 'gas_dvgw', 'name': 'Gasprüfung nach DVGW', 'desc': 'Gas Installation Test'}
    ],
    'UAE': [
        {'id': 'dewa_elec', 'name': 'DEWA Electrical Inspection', 'desc': 'Dubai Electricity & Water Authority Inspection'},
        {'id': 'civil_defense', 'name': 'Civil Defense Safety', 'desc': 'UAE Fire & Life Safety Certificate'}
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
        'Canada': 'CAN',
        'CAN': 'CAN',
        'Australia': 'AUS',
        'AUS': 'AUS',
        'Spain': 'ES',
        'ES': 'ES',
        'France': 'FR',
        'FR': 'FR',
        'Germany': 'DE',
        'DE': 'DE',
        'UAE': 'UAE',
        'United Arab Emirates': 'UAE'
    }
    
    normalized_code = mapping.get(country_code, 'UK')
    return CERTIFICATE_REGISTRY.get(normalized_code, CERTIFICATE_REGISTRY['UK'])
