from datetime import datetime
from db import get_db

# --- CONFIG: DATE FORMATS BY COUNTRY ---
COUNTRY_FORMATS = {
    'United Kingdom': '%d/%m/%Y',
    'United States': '%m/%d/%Y',
    'Default': '%d/%m/%Y'
}

def get_date_fmt_str(company_id):
    """Fetch the preferred date format string for a given company."""
    try:
        conn = get_db()
        if not conn:
            return COUNTRY_FORMATS['Default']
        cur = conn.cursor()
        
        # 1. Check for explicit date_format setting
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'date_format'", (company_id,))
        df_row = cur.fetchone()
        if df_row and df_row[0]:
            return df_row[0]
            
        # 2. Fallback to country_code
        cur.execute("SELECT value FROM settings WHERE company_id = %s AND key = 'country_code'", (company_id,))
        cc_row = cur.fetchone()
        
        # Map common country codes to their format
        if cc_row and cc_row[0]:
            code = cc_row[0].upper()
            if code == 'US': return '%m/%d/%Y'
            if code == 'UK': return '%d/%m/%Y'
            # Check dictionary fallback if they typed the full name
            return COUNTRY_FORMATS.get(code, '%d/%m/%Y')
            
        return COUNTRY_FORMATS['Default']
    except:
        return COUNTRY_FORMATS['Default']

def format_date(d, fmt_str='%d/%m/%Y'):
    """Format a date object or string into a target string format."""
    if not d: return ""
    try:
        if isinstance(d, str):
            try: 
                d = datetime.strptime(d, '%Y-%m-%d')
            except: 
                try: 
                    d = datetime.strptime(d, '%Y-%m-%d %H:%M:%S')
                except: 
                    return d
        return d.strftime(fmt_str)
    except: 
        return str(d)

def parse_date(d):
    """Parse a date string from the database back into a date object."""
    if isinstance(d, str):
        try: 
            return datetime.strptime(d, '%Y-%m-%d').date()
        except: 
            return None
    return d
