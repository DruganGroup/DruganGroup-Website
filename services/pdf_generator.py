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
    
    # --- SMART LOGO LOGIC (The Fix) ---
    if config.get('logo'):
        raw_logo = config['logo']
        final_logo_path = None

        # Case A: Path is already absolute and valid (e.g. /opt/render/...)
        if os.path.exists(raw_logo):
            final_logo_path = raw_logo
        
        # Case B: Path is 'file://' (e.g. file:///opt/render/...)
        elif raw_logo.startswith('file://'):
            clean = raw_logo.replace('file://', '')
            if os.path.exists(clean):
                final_logo_path = clean

        # Case C: Path is relative (e.g. /static/uploads/...) - Try to resolve it
        else:
            try:
                # Remove leading slash for join to work
                rel_path = raw_logo.lstrip('/')
                # Try finding it in root folder
                possible_path = os.path.join(current_app.root_path, rel_path)
                if os.path.exists(possible_path):
                    final_logo_path = possible_path
            except:
                pass

        # If we found a valid image, draw it
        if final_logo_path:
            try:
                if selected_theme == 'Minimal':
                    pdf.image(final_logo_path, 10, 10, 40)
                else:
                    pdf.image(final_logo_path, 10, 25, 50)
            except Exception as e:
                print(f"PDF Logo Error: {e}")

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
    tax_info = f"\nTax ID: {settings.get('tax_id')}" if settings.get('tax_id') else ""
        
    pdf.multi_cell(90, 5, f"{company.get('name')}\n{company_address}\n{settings.get('company_email', '')}{tax_info}")
    
    pdf.ln(10)

    # --- JOB CONTEXT BLOCK ---
    if invoice.get('job_title'):
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(*pdf.brand_color)
        pdf.cell(0, 6, f"PROJECT: {invoice.get('job_title')}", ln=True)
        
        if invoice.get('job_description'):
            pdf.set_font('Helvetica', 'I', 9)
            pdf.set_text_color(80)
            pdf.multi_cell(0, 5, f"{invoice.get('job_description')}")
        
        if not context.get('is_quote'):
            pdf.ln(2)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.set_text_color(50)
            pdf.cell(0, 5, f"Job Completed: {invoice.get('date')}", ln=True)
            
        pdf.ln(5) 

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
    pdf.set_draw_color(*pdf.brand_color)
    pdf.line(135, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(2)

    if vat_enabled:
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(155, 6, "Subtotal:", 0, 0, 'R')
        pdf.cell(35, 6, f"{cur_sym}{subtotal:.2f}  ", 0, 1, 'R')
        pdf.cell(155, 6, "Tax:", 0, 0, 'R')
        pdf.cell(35, 6, f"{cur_sym}{tax_amount:.2f}  ", 0, 1, 'R')
        pdf.set_draw_color(200, 200, 200)
        pdf.line(160, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(1)

    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(*pdf.brand_color) 
    pdf.cell(155, 10, "Grand Total:", 0, 0, 'R')
    pdf.cell(35, 10, f"{cur_sym}{grand_total:.2f}  ", 0, 1, 'R')
    
    # --- FOOTER ---
    pdf.set_y(-60)
    pdf.set_text_color(50)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 10, "Terms & Payment Details", ln=True)
    pdf.set_font('Helvetica', '', 9)
    
    terms = settings.get('payment_terms', 'Payment is due within 30 days.')
    bank = f"\nBank: {settings.get('bank_name')} | Sort: {settings.get('sort_code')} | Acc: {settings.get('account_number')}" if settings.get('bank_name') else ""
    
    pdf.multi_cell(0, 5, terms + bank)

    # --- SAVE ---
    save_dir = os.path.join(current_app.static_folder, 'uploads', 'documents')
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, output_filename)
    
    pdf.output(file_path)
    return file_path