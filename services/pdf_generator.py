import os
from fpdf import FPDF
from flask import current_app

class PDF(FPDF):
    def __init__(self, brand_color_hex, company_name):
        super().__init__()
        self.brand_color = self.hex_to_rgb(brand_color_hex)
        self.company_name = company_name
        
    def hex_to_rgb(self, hex_code):
        try:
            hex_code = hex_code.lstrip('#')
            return tuple(int(hex_code[i:i+2], 16) for i in (0, 2, 4))
        except:
            return (50, 50, 50) # Default dark grey if invalid

    def header(self):
        # 1. Brand Color Bar at top
        self.set_fill_color(*self.brand_color)
        self.rect(0, 0, 210, 20, 'F') # Full width banner
        self.ln(25)

    def footer(self):
        self.set_y(-30)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}/{{nb}} | {self.company_name}', align='C')

def generate_pdf(template_name_ignored, context, output_filename):
    """
    Generates a PDF using FPDF2 (High-End / Pixel Perfect).
    Ignores 'template_name' because we build it programmatically.
    """
    
    # 1. Setup Data
    invoice = context.get('invoice', {})
    items = context.get('items', [])
    settings = context.get('settings', {})
    config = context.get('config', {})
    company = context.get('company', {})
    
    brand_color = settings.get('brand_color', '#333333')
    
    # 2. Init PDF
    pdf = PDF(brand_color, company.get('name', 'Business Better'))
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    
    # --- LOGO SECTION ---
    # We resolve the absolute path to ensure it loads
    if config.get('logo'):
        # Convert '/static/...' to system path
        logo_rel_path = config['logo'].lstrip('/')
        logo_path = os.path.join(current_app.static_folder, '..', logo_rel_path)
        
        # If path starts with static/static, fix it (common Render issue)
        if 'static/static' in logo_path:
            logo_path = logo_path.replace('static/static', 'static')

        if os.path.exists(logo_path):
            try:
                # x=10, y=25, w=50 (width 50mm)
                pdf.image(logo_path, 10, 25, 50)
            except: pass # Skip if file corrupt
            
    # --- DOCUMENT TITLE (Right Side) ---
    pdf.set_y(25)
    pdf.set_font('Helvetica', 'B', 30)
    pdf.set_text_color(50)
    doc_type = "QUOTE" if context.get('is_quote') else "INVOICE"
    pdf.cell(0, 10, doc_type, ln=True, align='R')
    
    pdf.set_font('Helvetica', '', 12)
    pdf.set_text_color(100)
    pdf.cell(0, 8, f"#{invoice.get('ref', '000')}", ln=True, align='R')
    pdf.cell(0, 8, f"Date: {invoice.get('date')}", ln=True, align='R')
    
    pdf.ln(20) # Spacer

    # --- ADDRESS BLOCKS (Side by Side) ---
    y_start = pdf.get_y()
    
    # LEFT: Bill To
    pdf.set_x(10)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(90, 6, "BILL TO:", ln=True)
    
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    pdf.multi_cell(90, 5, f"{invoice.get('client_name')}\n{invoice.get('client_address') or ''}\n{invoice.get('client_email')}")
    
    # RIGHT: From (Manually move cursor back up and right)
    pdf.set_y(y_start)
    pdf.set_x(110)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(90, 6, "FROM:", ln=True)
    
    pdf.set_x(110)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    company_address = settings.get('company_address', 'Registered Office')
    company_email = settings.get('company_email', '')
    pdf.multi_cell(90, 5, f"{company.get('name')}\n{company_address}\n{company_email}")
    
    pdf.ln(20)

    # --- ITEMS TABLE HEADER ---
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_fill_color(*pdf.brand_color) # Background Color
    pdf.set_text_color(255) # White Text
    
    # Widths: Desc(100), Qty(25), Price(30), Total(35)
    pdf.cell(100, 10, "  Description", 0, 0, 'L', True)
    pdf.cell(25, 10, "Qty", 0, 0, 'C', True)
    pdf.cell(30, 10, "Price", 0, 0, 'R', True)
    pdf.cell(35, 10, "Total  ", 0, 1, 'R', True) # ln=1 moves to next line

    # --- ITEMS ROWS ---
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    fill = False # Alternating rows flag
    pdf.set_fill_color(245, 245, 245) # Light grey for alternate rows

    for item in items:
        # Check for page break
        if pdf.get_y() > 250:
            pdf.add_page()
            # Reprint Header
            pdf.set_font('Helvetica', 'B', 10)
            pdf.set_fill_color(*pdf.brand_color) 
            pdf.set_text_color(255) 
            pdf.cell(100, 10, "  Description", 0, 0, 'L', True)
            pdf.cell(25, 10, "Qty", 0, 0, 'C', True)
            pdf.cell(30, 10, "Price", 0, 0, 'R', True)
            pdf.cell(35, 10, "Total  ", 0, 1, 'R', True)
            pdf.set_font('Helvetica', '', 10)
            pdf.set_text_color(50)

        pdf.cell(100, 10, f"  {item.get('desc')}", 0, 0, 'L', fill)
        pdf.cell(25, 10, str(item.get('qty')), 0, 0, 'C', fill)
        pdf.cell(30, 10, f"£{item.get('price'):.2f}", 0, 0, 'R', fill)
        pdf.cell(35, 10, f"£{item.get('total'):.2f}  ", 0, 1, 'R', fill)
        fill = not fill # Toggle color

    # --- TOTALS SECTION ---
    pdf.ln(5)
    
    # Draw a line above totals
    pdf.set_draw_color(*pdf.brand_color)
    pdf.line(135, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    pdf.set_font('Helvetica', 'B', 12)
    pdf.cell(155, 10, "Grand Total:", 0, 0, 'R')
    
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(35, 10, f"£{invoice.get('total'):.2f}  ", 0, 1, 'R')
    
    # --- FOOTER / TERMS ---
    pdf.set_y(-60)
    pdf.set_text_color(50)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 10, "Terms & Payment Details", ln=True)
    
    pdf.set_font('Helvetica', '', 9)
    terms = "Payment is due within 30 days."
    bank = ""
    if settings.get('bank_name'):
        bank = f"\nBank: {settings.get('bank_name')} | Sort: {settings.get('sort_code')} | Acc: {settings.get('account_number')}"
    
    pdf.multi_cell(0, 5, terms + bank)

    # --- SAVE FILE ---
    save_dir = os.path.join(current_app.static_folder, 'uploads', 'documents')
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, output_filename)
    
    pdf.output(file_path)
    return file_path