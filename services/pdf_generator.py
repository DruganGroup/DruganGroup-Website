import os
import base64
import tempfile
from decimal import Decimal
from fpdf import FPDF
from flask import current_app

class BasePDF(FPDF):
    def __init__(self, brand_color_hex, company_name):
        super().__init__()
        self.brand_color = self.hex_to_rgb(brand_color_hex)
        self.company_name = company_name
        
    def hex_to_rgb(self, hex_code):
        try:
            hex_code = hex_code.lstrip('#')
            return tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))
        except:
            return (50, 50, 50)

    def footer(self):
        self.set_y(-20)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}} | {self.company_name}', align='C')

# --- THEMES ---
class ModernPDF(BasePDF):
    def header(self):
        self.set_fill_color(*self.brand_color)
        self.rect(0, 0, 210, 20, 'F')
        self.ln(25)

class ClassicPDF(BasePDF):
    def header(self):
        self.ln(10)
        self.set_draw_color(*self.brand_color)
        self.set_line_width(1)
        self.line(10, 35, 200, 35) 

# --- HELPER: SAVE BASE64 IMAGE ---
def save_base64_image(data_str):
    if not data_str or 'base64,' not in data_str: return None
    try:
        header, encoded = data_str.split('base64,', 1)
        data = base64.b64decode(encoded)
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
            f.write(data)
            return f.name
    except:
        return None

# =========================================================
# 1. CP12 GENERATOR (GAS SAFETY)
# =========================================================
def generate_cp12(context, file_path):
    prop = context.get('prop', {})
    data = context.get('data', {})
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Header
    pdf.set_font('Helvetica', 'B', 20)
    pdf.set_text_color(220, 53, 69) # Red header
    pdf.cell(0, 10, "GAS SAFETY RECORD (CP12)", ln=True, align='L')
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(0)
    pdf.cell(0, 6, f"Date: {context.get('today')}", ln=True)
    pdf.ln(5)

    # Site Details Box
    pdf.set_fill_color(240, 240, 240)
    pdf.rect(10, 35, 90, 30, 'F')
    pdf.set_xy(12, 37)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 5, "Site Details", ln=True)
    pdf.set_font('Helvetica', '', 9)
    pdf.multi_cell(85, 5, f"Tenant: {prop.get('client')}\nAddress: {prop.get('address')}")

    # Engineer Details Box
    pdf.rect(110, 35, 90, 30, 'F')
    pdf.set_xy(112, 37)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 5, "Engineer Details", ln=True)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_xy(112, 42)
    pdf.multi_cell(85, 5, f"Name: {context.get('session_user_name')}\nCompany: Business Better")

    pdf.set_y(70)
    pdf.ln(5)

    # Appliance Table Header
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_fill_color(50, 50, 50)
    pdf.set_text_color(255)
    cols = [30, 30, 30, 30, 20, 20, 30]
    headers = ["Location", "Type", "Make/Model", "Pressure", "Combust", "Vent", "Safe?"]
    
    for i, h in enumerate(headers):
        pdf.cell(cols[i], 8, h, 1, 0, 'C', True)
    pdf.ln()

    # Appliance Row (From Data)
    pdf.set_text_color(0)
    pdf.set_font('Helvetica', '', 8)
    
    # We map the flat data to a row
    row_data = [
        data.get('loc', ''),
        data.get('type', ''),
        f"{data.get('make','')}/{data.get('model','')}",
        f"{data.get('pressure','')} mbar",
        data.get('comb', '-'),
        data.get('vent', '-'),
        data.get('safe', 'NO')
    ]
    
    for i, txt in enumerate(row_data):
        pdf.cell(cols[i], 8, str(txt), 1, 0, 'C')
    pdf.ln()
    
    # Filler rows
    for _ in range(3):
        for i in range(len(cols)): pdf.cell(cols[i], 8, "", 1, 0, 'C')
        pdf.ln()

    pdf.ln(10)

    # Checklist
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 8, "Inspection Results", ln=True)
    pdf.set_font('Helvetica', '', 10)
    
    checks = [
        ("Gas Tightness Test Passed?", data.get('gas_tight', False)),
        ("CO Alarm Tested & Working?", data.get('co_alarm', False))
    ]
    
    for label, val in checks:
        status = "PASS" if val or val == 'on' else "FAIL / NO"
        pdf.cell(100, 6, label, 0, 0)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(0, 6, status, 0, 1)
        pdf.set_font('Helvetica', '', 10)

    pdf.ln(10)
    
    # Signature
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 8, "Declaration", ln=True)
    pdf.set_font('Helvetica', '', 9)
    pdf.multi_cell(0, 5, "I certify that the appliances detailed above have been checked for safety in accordance with the Gas Safety (Installation and Use) Regulations.")
    pdf.ln(5)
    
    sig_file = save_base64_image(data.get('signature_img'))
    if sig_file:
        pdf.image(sig_file, x=pdf.get_x(), y=pdf.get_y(), w=50)
        os.unlink(sig_file) # Clean up temp file
    
    pdf.ln(25)
    pdf.cell(0, 6, f"Next Inspection Due: {context.get('next_year_date')}", ln=True)

    pdf.output(file_path)
    return file_path

# =========================================================
# 2. EICR GENERATOR (ELECTRICAL)
# =========================================================
def generate_eicr(context, file_path):
    prop = context.get('prop', {})
    data = context.get('data', {})
    
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # Header
    pdf.set_font('Helvetica', 'B', 20)
    pdf.set_text_color(0, 86, 179) # Blue header
    pdf.cell(0, 10, "EICR - Electrical Condition Report", ln=True, align='L')
    pdf.ln(5)
    
    # Details
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(0)
    pdf.cell(0, 6, f"Address: {prop.get('address')}", ln=True)
    pdf.cell(0, 6, f"Client: {prop.get('client')}", ln=True)
    pdf.ln(5)
    
    # System Info
    pdf.set_fill_color(230, 230, 230)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 8, "  Installation Details", 0, 1, 'L', True)
    pdf.set_font('Helvetica', '', 10)
    pdf.ln(2)
    pdf.cell(60, 6, f"Earthing: {data.get('earthing_type')}", 0, 0)
    pdf.cell(60, 6, f"Fuse: {data.get('main_fuse')} A", 0, 0)
    pdf.cell(60, 6, f"Ze: {data.get('ze')} Ohms", 0, 1)
    pdf.ln(5)

    # Circuits Table
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(0, 8, "  Circuit Schedule", 0, 1, 'L', True)
    
    headers = ["No", "Desc", "Type", "Rating", "Cable", "RCD", "Zs"]
    w = [10, 50, 20, 20, 20, 20, 20]
    
    for i, h in enumerate(headers):
        pdf.cell(w[i], 7, h, 1, 0, 'C')
    pdf.ln()
    
    pdf.set_font('Helvetica', '', 8)
    circuits = data.get('circuits', [])
    
    if circuits:
        for c in circuits:
            pdf.cell(w[0], 6, str(c.get('id', '')), 1, 0, 'C')
            pdf.cell(w[1], 6, str(c.get('desc', '')), 1, 0, 'L')
            pdf.cell(w[2], 6, str(c.get('type', '')), 1, 0, 'C')
            pdf.cell(w[3], 6, str(c.get('rating', '')), 1, 0, 'C')
            pdf.cell(w[4], 6, str(c.get('cable', '')), 1, 0, 'C')
            pdf.cell(w[5], 6, str(c.get('rcd', '')), 1, 0, 'C')
            pdf.cell(w[6], 6, str(c.get('zs', '')), 1, 1, 'C')
    else:
        pdf.cell(0, 6, "No circuits recorded", 1, 1, 'C')

    pdf.ln(5)
    
    # Observations
    pdf.set_font('Helvetica', 'B', 9)
    pdf.cell(0, 8, "  Observations", 0, 1, 'L', True)
    pdf.set_font('Helvetica', '', 9)
    
    obs = data.get('observations', [])
    if obs:
        for o in obs:
            pdf.cell(150, 6, f"- {o.get('desc')}", 0, 0)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.cell(30, 6, o.get('code'), 0, 1, 'R')
            pdf.set_font('Helvetica', '', 9)
    else:
        pdf.cell(0, 6, "No defects observed.", 0, 1)

    pdf.ln(10)
    
    # Result
    status = data.get('status', 'Issued')
    color = (0, 128, 0) if data.get('outcome') == 'Satisfactory' else (200, 0, 0)
    
    pdf.set_font('Helvetica', 'B', 14)
    pdf.set_text_color(*color)
    pdf.cell(0, 10, f"Outcome: {data.get('outcome', 'Not Set').upper()}", ln=True, align='C')
    
    pdf.output(file_path)
    return file_path


# =========================================================
# 3. MAIN ROUTER (The Invoice/Quote Logic)
# =========================================================
def generate_pdf(template_name, context, output_filename):
    """
    Main entry point. Routes to specific generator based on filename/template.
    """
    # 1. SETUP PATHS
    save_dir = os.path.join(current_app.static_folder, 'uploads', 'documents')
    os.makedirs(save_dir, exist_ok=True)
    
    # If absolute path provided (via office_routes fix), use it. Else use default.
    if os.path.isabs(output_filename):
        file_path = output_filename
    else:
        file_path = os.path.join(save_dir, output_filename)

    # 2. ROUTE TO SPECIALTY GENERATORS
    if 'cp12' in str(template_name).lower() or 'gas' in str(template_name).lower():
        return generate_cp12(context, file_path)
    
    if 'eicr' in str(template_name).lower():
        return generate_eicr(context, file_path)

    # 3. FALLBACK: STANDARD INVOICE/QUOTE LOGIC (Your existing code)
    invoice = context.get('invoice', {})
    items = context.get('items', [])
    settings = context.get('settings', {})
    config = context.get('config', {})
    company = context.get('company', {})
    
    brand_color = settings.get('brand_color', '#333333')
    cur_sym = settings.get('currency_symbol', '£')
    selected_theme = settings.get('pdf_theme', 'Modern')
    
    # Init PDF
    if selected_theme == 'Classic':
        pdf = ClassicPDF(brand_color, company.get('name', ''))
    elif selected_theme == 'Minimal':
        pdf = MinimalPDF(brand_color, company.get('name', ''))
    else:
        pdf = ModernPDF(brand_color, company.get('name', ''))

    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # --- LOGO LOGIC ---
    if config.get('logo'):
        raw_logo = config['logo']
        final_logo_path = None
        if os.path.exists(raw_logo):
            final_logo_path = raw_logo
        elif '/static/' in raw_logo:
            try:
                clean_path = raw_logo.split('/static/')[-1]
                possible_path = os.path.join(current_app.static_folder, clean_path)
                if os.path.exists(possible_path): final_logo_path = possible_path
            except: pass
        
        if final_logo_path:
            try: pdf.image(final_logo_path, 10, 10 if selected_theme=='Minimal' else 25, 40 if selected_theme=='Minimal' else 50)
            except: pass

    # --- HEADER ---
    pdf.set_y(25 if selected_theme != 'Minimal' else 15)
    pdf.set_font('Helvetica', 'B', 30 if selected_theme != 'Minimal' else 24)
    pdf.set_text_color(50)
    
    doc_type = "QUOTE" if context.get('is_quote') else "INVOICE"
    align = 'R' if selected_theme != 'Minimal' else 'L'
    if selected_theme == 'Minimal': pdf.set_xy(120, 15)
    
    pdf.cell(0, 10, doc_type, ln=True, align=align)
    
    pdf.set_font('Helvetica', '', 12)
    pdf.set_text_color(100)
    if selected_theme == 'Minimal': pdf.set_x(120)
    pdf.cell(0, 8, f"#{invoice.get('ref', '000')}", ln=True, align=align)
    if selected_theme == 'Minimal': pdf.set_x(120)
    pdf.cell(0, 8, f"Date: {invoice.get('date')}", ln=True, align=align)
    
    pdf.ln(20)

    # --- ADDRESSES ---
    y_start = pdf.get_y()
    pdf.set_x(10)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(90, 6, "BILL TO:", ln=True)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    pdf.multi_cell(90, 5, f"{invoice.get('client_name')}\n{invoice.get('client_address') or ''}\n{invoice.get('client_email')}")
    
    pdf.set_y(y_start)
    pdf.set_x(110)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(90, 6, "FROM:", ln=True)
    pdf.set_x(110)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    company_address = settings.get('company_address', 'Registered Office')
    pdf.multi_cell(90, 5, f"{company.get('name')}\n{company_address}\n{settings.get('company_email', '')}")
    
    pdf.ln(10)

    # --- TABLE ---
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(*pdf.brand_color) 
    pdf.set_text_color(255) 
    pdf.cell(100, 10, "  Description", 0, 0, 'L', True)
    pdf.cell(25, 10, "Qty", 0, 0, 'C', True)
    pdf.cell(30, 10, "Price", 0, 0, 'R', True)
    pdf.cell(35, 10, "Total  ", 0, 1, 'R', True)

    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    fill = False 
    pdf.set_fill_color(245, 245, 245)

    for item in items:
        pdf.cell(100, 10, f"  {item.get('desc')}", 0, 0, 'L', fill)
        pdf.cell(25, 10, str(item.get('qty')), 0, 0, 'C', fill)
        pdf.cell(30, 10, f"{cur_sym}{item.get('price'):.2f}", 0, 0, 'R', fill)
        pdf.cell(35, 10, f"{cur_sym}{item.get('total'):.2f}  ", 0, 1, 'R', fill)
        fill = not fill 

    # --- TOTALS ---
    subtotal = sum(Decimal(str(item.get('total', 0))) for item in items)
    vat_enabled = settings.get('vat_registered') == 'yes'
    tax_rate = Decimal('0.20') if vat_enabled else Decimal('0.00')
    tax_amount = subtotal * tax_rate
    grand_total = subtotal + tax_amount

    pdf.ln(5)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(*pdf.brand_color) 
    pdf.cell(155, 10, "Grand Total:", 0, 0, 'R')
    pdf.cell(35, 10, f"{cur_sym}{grand_total:.2f}  ", 0, 1, 'R')
    
    pdf.output(file_path)
    return file_path