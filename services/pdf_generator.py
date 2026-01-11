import os
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

class MinimalPDF(BasePDF):
    def header(self):
        self.ln(15)

def generate_pdf(template_name_ignored, context, output_filename):
    """
    Generates PDF based on settings (Theme & Currency).
    """
    invoice = context.get('invoice', {})
    items = context.get('items', [])
    settings = context.get('settings', {})
    config = context.get('config', {})
    company = context.get('company', {})
    
    brand_color = settings.get('brand_color', '#333333')
    
    # 1. GET CURRENCY SYMBOL (Defaults to £ if missing)
    cur_sym = settings.get('currency_symbol', '£')
    
    # 2. SELECT THEME
    selected_theme = settings.get('pdf_theme', 'Modern')
    
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
        logo_rel_path = config['logo'].lstrip('/')
        logo_path = os.path.join(current_app.static_folder, '..', logo_rel_path)
        if 'static/static' in logo_path: logo_path = logo_path.replace('static/static', 'static')

        if os.path.exists(logo_path):
            try:
                if selected_theme == 'Minimal':
                    pdf.image(logo_path, 10, 10, 40)
                else:
                    pdf.image(logo_path, 10, 25, 50)
            except: pass

    # --- DOCUMENT HEADER ---
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

# --- ADDRESS BLOCKS ---
    y_start = pdf.get_y()
    
    # LEFT: Bill To
    pdf.set_x(10)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(90, 6, "BILL TO:", ln=True)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    pdf.multi_cell(90, 5, f"{invoice.get('client_name')}\n{invoice.get('client_address') or ''}\n{invoice.get('client_email')}")
    
    # RIGHT: From
    pdf.set_y(y_start)
    pdf.set_x(110)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*pdf.brand_color)
    pdf.cell(90, 6, "FROM:", ln=True)
    pdf.set_x(110)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(50)
    company_address = settings.get('company_address', 'Registered Office')
    
    tax_info = ""
    if settings.get('tax_id'):
        tax_info = f"\nTax ID: {settings.get('tax_id')}"
        
    pdf.multi_cell(90, 5, f"{company.get('name')}\n{company_address}\n{settings.get('company_email', '')}{tax_info}")
    
    pdf.ln(10)

    # --- NEW: JOB CONTEXT BLOCK ---
    # Shows Title & Description on BOTH Quotes and Invoices
    if invoice.get('job_title'):
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(*pdf.brand_color)
        pdf.cell(0, 6, f"PROJECT: {invoice.get('job_title')}", ln=True)
        
        if invoice.get('job_description'):
            pdf.set_font('Helvetica', 'I', 9)
            pdf.set_text_color(80)
            pdf.multi_cell(0, 5, f"{invoice.get('job_description')}")
        
        # ADDED: "Job Completed" line for Invoices
        if not context.get('is_quote'):
            pdf.ln(2)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(50)
            # We use the Invoice Date as the completion date
            pdf.cell(0, 5, f"Job Completed: {invoice.get('date')}", ln=True)
            
        pdf.ln(5) 
    # --- END NEW BLOCK ---

    pdf.ln(5)

    # --- ITEMS TABLE ---
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
        if pdf.get_y() > 250:
            pdf.add_page()
            # Reprint Header if page break
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
        
        # --- HERE IS THE CURRENCY FIX ---
        pdf.cell(30, 10, f"{cur_sym}{item.get('price'):.2f}", 0, 0, 'R', fill)
        pdf.cell(35, 10, f"{cur_sym}{item.get('total'):.2f}  ", 0, 1, 'R', fill)
        
        fill = not fill 

    # --- TOTALS & TAX CALCULATION ---
    # 1. Calculate Subtotal (Ensure it's a Decimal)
    subtotal = sum(Decimal(str(item.get('total', 0))) for item in items)
    
    # 2. Check Tax Status & Country
    vat_enabled = settings.get('vat_registered') == 'yes'
    country = settings.get('country_code', 'UK')
    
    # 3. Determine Tax Rate (As Decimal)
    tax_rate = Decimal('0.00')
    tax_name = "Tax"
    
    if vat_enabled:
        if country == 'UK':
            tax_rate = Decimal('0.20'); tax_name = "VAT (20%)"
        elif country == 'AUS':
            tax_rate = Decimal('0.10'); tax_name = "GST (10%)"
        elif country == 'NZ':
            tax_rate = Decimal('0.15'); tax_name = "GST (15%)"
        elif country == 'CAN':
            tax_rate = Decimal('0.05'); tax_name = "GST (5%)"
        elif country == 'EU':
            tax_rate = Decimal('0.21'); tax_name = "VAT (21%)"
        else:
            tax_rate = Decimal('0.00'); tax_name = "Tax (0%)"

    # Now we multiply Decimal * Decimal (Safe!)
    tax_amount = subtotal * tax_rate
    grand_total = subtotal + tax_amount

    # --- DRAW TOTALS SECTION ---
    pdf.ln(5)
    pdf.set_draw_color(*pdf.brand_color)
    pdf.line(135, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    if vat_enabled:
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(155, 6, "Subtotal:", 0, 0, 'R')
        pdf.cell(35, 6, f"{cur_sym}{subtotal:.2f}  ", 0, 1, 'R')
        
        pdf.cell(155, 6, tax_name + ":", 0, 0, 'R')
        pdf.cell(35, 6, f"{cur_sym}{tax_amount:.2f}  ", 0, 1, 'R')
        
        # Extra line
        pdf.set_draw_color(200, 200, 200)
        pdf.line(160, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(1)

    # Grand Total
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(*pdf.brand_color) 
    pdf.cell(155, 10, "Grand Total:", 0, 0, 'R')
    pdf.cell(35, 10, f"{cur_sym}{grand_total:.2f}  ", 0, 1, 'R')
    
    # --- FOOTER / TERMS ---
    pdf.set_y(-60)
    pdf.set_text_color(50)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 10, "Terms & Payment Details", ln=True)
    
    pdf.set_font('Helvetica', '', 9)
    terms = settings.get('payment_terms', 'Payment is due within 30 days.')
    bank = ""
    if settings.get('bank_name'):
        bank = f"\nBank: {settings.get('bank_name')} | Sort/Route: {settings.get('sort_code')} | Acc: {settings.get('account_number')}"
    
    pdf.multi_cell(0, 5, terms + bank)

    # --- SAVE FILE ---
    save_dir = os.path.join(current_app.static_folder, 'uploads', 'documents')
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, output_filename)
    
    pdf.output(file_path)
    return file_path