import os
import re
import json
from datetime import date

# Safely import Google AI so it never crashes the app startup
try:
    import google.generativeai as genai
except ImportError:
    genai = None

def encode_image(image_path):
    """Reads image file for AI processing"""
    with open(image_path, "rb") as image_file:
        return image_file.read()

# --- TIER 1: REGEX SCANNER (Fast & Free) ---
def run_regex_scan(filename):
    result = {
        'found': False,
        'data': {
            'job_ref': None,
            'doc_type': 'Unknown',
            'total_cost': 0.0,
            'date': str(date.today()),
            'vendor': 'Unknown'
        }
    }
    
    # Hunt for Job References
    job_match = re.search(r'(job|ref|inv|j)[-_\s:.]?(\d{3,})', filename.lower())
    if job_match:
        result['data']['job_ref'] = job_match.group(2)
        result['found'] = True

    # Hunt for Document Type
    fname = filename.lower()
    if 'invoice' in fname: result['data']['doc_type'] = 'supplier_invoice'
    elif any(x in fname for x in ['receipt', 'fuel', 'petrol', 'diesel']): 
        result['data']['doc_type'] = 'fuel_receipt'
    elif 'quote' in fname: result['data']['doc_type'] = 'quote'
    elif 'cert' in fname: result['data']['doc_type'] = 'certificate'

    # Hunt for Costs
    cost_match = re.search(r'(\d+\.\d{2})', filename)
    if cost_match:
        result['data']['total_cost'] = float(cost_match.group(1))
        
    return result

# --- TIER 2: GOOGLE GEMINI SCANNER (Uses Tenant API Key) ---
def run_gemini_scan(file_path, api_key=None, context_materials=None, context_suppliers=None):
    if not genai:
        return {'success': False, 'error': "google-generativeai package is not installed."}

    # Force reliance on Tenant API key passed from database
    if not api_key: 
        return {'success': False, 'error': "No Tenant Google AI API Key provided in settings."}

    try:
        # Configure dynamically using the tenant's API key
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        image_data = encode_image(file_path)
        
        prompt = f"""
        Analyze this document image. Extract the following fields as valid JSON only:
        {{
            "doc_type": "supplier_invoice" or "fuel_receipt" or "certificate",
            "job_ref": "Look for Job Numbers like JOB-101, J-105, or Project References",
            "total_cost": 0.00,
            "date": "YYYY-MM-DD",
            "vendor": "Company Name",
            "vehicle_reg": "Vehicle Registration if found",
            "line_items": [
                {{
                    "description": "Item name",
                    "quantity": 0.00,
                    "unit_price": 0.00
                }}
            ]
        }}
        If a field is missing, set it to null. Do not include markdown formatting.
        Context constraints:
        - Known Suppliers: {context_suppliers or 'None'}
        - Known Materials: {context_materials or 'None'}
        If the vendor or a material matches closely with the known context, use the exact name from the context to prevent duplicates.
        """
        
        response = model.generate_content([
            {'mime_type': 'image/jpeg', 'data': image_data},
            prompt
        ])
        
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(clean_text)
        
        return {'success': True, 'data': data}
        
    except Exception as e:
        print(f"Gemini Error: {e}")
        return {'success': False, 'error': str(e)}

# --- MAIN CONTROLLER ---
def universal_sort_document(file_path, api_key=None, context_materials=None, context_suppliers=None):
    filename = os.path.basename(file_path)
    
    # 1. RUN REGEX (Tier 1)
    regex_result = run_regex_scan(filename)
    
    if regex_result['found'] and regex_result['data']['job_ref']:
        return {
            'success': True, 
            'result': {
                'doc_type': regex_result['data']['doc_type'],
                'confidence': 100,
                'data': regex_result['data']
            }
        }

    # 2. RUN GEMINI AI (Tier 2) - Uses Tenant Key
    ai_result = run_gemini_scan(file_path, api_key, context_materials, context_suppliers)
    
    if ai_result['success']:
        data = ai_result['data']
        if data.get('job_ref'):
            return {
                'success': True, 
                'result': {
                    'doc_type': data.get('doc_type', 'Unknown'),
                    'confidence': 90,
                    'data': data
                }
            }
    
    # 3. FALLBACK TO MANUAL (Tier 3)
    return {
        'success': True,
        'result': {
            'doc_type': 'Needs Review',
            'confidence': 0,
            'data': regex_result['data']
        }
    }

def extract_receipt_materials(file_path, api_key=None, context_materials=None, context_suppliers=None):
    return run_gemini_scan(file_path, api_key, context_materials, context_suppliers)