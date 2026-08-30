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
    'IE': [
        {'id': 'rgii_gas', 'name': 'RGII Gas Certificate', 'desc': 'Registered Gas Installer Certificate'},
        {'id': 'safe_elec', 'name': 'Safe Electric (RECI)', 'desc': 'Electrical Completion Certificate'},
        {'id': 'ber_cert', 'name': 'BER Certificate', 'desc': 'Building Energy Rating Certificate'}
    ],
    'NZ': [
        {'id': 'esc_elec', 'name': 'ESC Electrical Certificate', 'desc': 'Electrical Safety Certificate (NZ)'},
        {'id': 'gas_nz', 'name': 'Gas Safety Certificate', 'desc': 'New Zealand Gas Safety Certificate'}
    ],
    'UAE': [
        {'id': 'dewa_elec', 'name': 'DEWA Electrical Inspection', 'desc': 'Dubai Electricity & Water Authority Inspection'},
        {'id': 'civil_defense', 'name': 'Civil Defense Safety', 'desc': 'UAE Fire & Life Safety Certificate'}
    ]
}

COUNTRY_COMPLIANCE_LABELS = {
    'UK': {
        'gas': {'short': 'GAS', 'full': 'Gas Safety (CP12)', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'EICR', 'full': 'Electrical (EICR)', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'PAT', 'full': 'PAT Testing', 'icon': 'fas fa-plug'},
        'epc': {'short': 'EPC', 'full': 'Energy (EPC)', 'icon': 'fas fa-leaf'}
    },
    'ES': {
        'gas': {'short': 'GAS', 'full': 'Boletín de Gas', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'CIE', 'full': 'Boletín Eléctrico (CIE)', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'ITP', 'full': 'Inspección Técnica (ITP)', 'icon': 'fas fa-plug'},
        'epc': {'short': 'CEE', 'full': 'Certificado Energético', 'icon': 'fas fa-leaf'}
    },
    'FR': {
        'gas': {'short': 'GAS', 'full': 'Certificat Qualigaz', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'ELEC', 'full': 'Attestation Consuel', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'SEC', 'full': 'Contrôle Sécurité', 'icon': 'fas fa-plug'},
        'epc': {'short': 'DPE', 'full': 'DPE (Diagnostic Énergie)', 'icon': 'fas fa-leaf'}
    },
    'DE': {
        'gas': {'short': 'GAS', 'full': 'Gasprüfung (DVGW)', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'DGUV', 'full': 'DGUV V3 Prüfprotokoll', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'VDE', 'full': 'Geräteprüfung (VDE)', 'icon': 'fas fa-plug'},
        'epc': {'short': 'GEG', 'full': 'Energieausweis (GEG)', 'icon': 'fas fa-leaf'}
    },
    'US': {
        'gas': {'short': 'GAS', 'full': 'Gas / HVAC Safety', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'NFPA', 'full': 'NFPA 70E Electrical', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'OSHA', 'full': 'OSHA Safety Audit', 'icon': 'fas fa-plug'},
        'epc': {'short': 'EPA', 'full': 'EPA Energy Audit', 'icon': 'fas fa-leaf'}
    },
    'CAN': {
        'gas': {'short': 'TSSA', 'full': 'TSSA Gas Inspection', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'ESA', 'full': 'ESA Electrical Defect/Cert', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'CSA', 'full': 'CSA Safety Audit', 'icon': 'fas fa-plug'},
        'epc': {'short': 'ENG', 'full': 'EnerGuide Audit', 'icon': 'fas fa-leaf'}
    },
    'AUS': {
        'gas': {'short': 'GAS', 'full': 'Plumbing & Gas CoC', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'CCEW', 'full': 'CCEW Electrical Work', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'TAG', 'full': 'Test & Tag (Safety)', 'icon': 'fas fa-plug'},
        'epc': {'short': 'NatH', 'full': 'NatHERS Energy Rating', 'icon': 'fas fa-leaf'}
    },
    'NZ': {
        'gas': {'short': 'GAS', 'full': 'Gas Safety Certificate', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'ESC', 'full': 'ESC Electrical Cert', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'TAG', 'full': 'Test & Tag (Safety)', 'icon': 'fas fa-plug'},
        'epc': {'short': 'NZGBC', 'full': 'HomeStar / Energy Cert', 'icon': 'fas fa-leaf'}
    },
    'IE': {
        'gas': {'short': 'RGII', 'full': 'RGII Gas Certificate', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'RECI', 'full': 'Safe Electric (RECI)', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'PAT', 'full': 'PAT Testing', 'icon': 'fas fa-plug'},
        'epc': {'short': 'BER', 'full': 'BER (Building Energy)', 'icon': 'fas fa-leaf'}
    },
    'UAE': {
        'gas': {'short': 'GAS', 'full': 'Civil Defense Gas Safety', 'icon': 'fas fa-fire'},
        'eicr': {'short': 'DEWA', 'full': 'DEWA Electrical Inspection', 'icon': 'fas fa-bolt'},
        'pat': {'short': 'CIVIL', 'full': 'Civil Defense Life Safety', 'icon': 'fas fa-shield-alt'},
        'epc': {'short': 'GREEN', 'full': 'Estidama / Green Building', 'icon': 'fas fa-leaf'}
    }
}

def normalize_country_code(country_code):
    if not country_code:
        return 'UK'
    mapping = {
        'United Kingdom': 'UK', 'UK': 'UK', 'GB': 'UK',
        'United States': 'US', 'US': 'US', 'USA': 'US',
        'Canada': 'CAN', 'CAN': 'CAN', 'CA': 'CAN',
        'Australia': 'AUS', 'AUS': 'AUS', 'AU': 'AUS',
        'Spain': 'ES', 'ES': 'ES',
        'France': 'FR', 'FR': 'FR',
        'Germany': 'DE', 'DE': 'DE',
        'Ireland': 'IE', 'IE': 'IE',
        'New Zealand': 'NZ', 'NZ': 'NZ',
        'UAE': 'UAE', 'United Arab Emirates': 'UAE'
    }
    return mapping.get(str(country_code).strip(), 'UK')

def get_certificates_for_country(country_code):
    """
    Returns the list of certificates applicable to a given country code.
    Defaults to UK if country code is not explicitly supported yet.
    """
    code = normalize_country_code(country_code)
    return CERTIFICATE_REGISTRY.get(code, CERTIFICATE_REGISTRY['UK'])

def get_country_compliance_labels(country_code):
    """
    Returns the regional labels and icons for gas, electrical, safety, and energy compliance.
    """
    code = normalize_country_code(country_code)
    return COUNTRY_COMPLIANCE_LABELS.get(code, COUNTRY_COMPLIANCE_LABELS['UK'])
