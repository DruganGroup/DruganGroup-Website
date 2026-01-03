import os
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

# --- THEME 1: MODERN (The one you just approved) ---
class ModernPDF(BasePDF):
    def header(self):
        self.set_fill_color(*self.brand_color)
        self.rect(0, 0, 210, 20, 'F')
        self.ln(25)

# --- THEME 2: CLASSIC (Traditional, Boxed Layout) ---
class ClassicPDF(BasePDF):
    def header(self):
        self.ln(10)
        # No colored banner, just a clean line
        self.set_draw_color(*self.brand_color)
        self.set_line_width(1)
        self.line(10, 35, 200, 35) 

# --- THEME 3: MINIMAL (Clean, Left-Aligned) ---
class MinimalPDF(BasePDF):
    def header(self):
        self.ln(15)
        # Very simple, just the logo and text

def generate_pdf(template_name, context, output_filename):
    """
    Generates PDF based on the selected theme in settings.
    """
    invoice = context.get('invoice', {})
    items = context.get('items', [])
    settings = context.get('settings', {})
    config = context.get('config', {})
    company = context.get('company', {})
    
    brand_color = settings.get('brand_color', '#333333')
    
    # 1. SELECT THEME (Default to Modern)
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
    
    # --- LOGO LOGIC (Common to all) ---
    if config.get('logo'):
        logo_rel_path = config['logo'].lstrip('/')
        logo_path = os.path.join(current_app.static_folder, '..', logo_rel_path)
        if 'static/static' in logo_path: logo_path = logo_path.replace('static/static', 'static')

        if os.path.exists(logo_path):
            try:
                # Different logo positions for different themes
                if selected_theme == 'Minimal':
                    pdf.image(logo_path, 10, 10, 40)
                else:
                    pdf.image(logo_path, 10, 25, 50)
            except: pass

    # --- DOCUMENT CONTENT (Simplified for this example) ---
    # You can customize the layout per theme here using `if selected_theme == ...`
    
    pdf.set_y(25 if selected_theme != 'Minimal' else 15)
    pdf.set_font('Helvetica', 'B', 30 if selected_theme != 'Minimal' else 24)
    pdf.set_text_color(50)
    
    doc_type = "QUOTE" if context.get('is_quote') else "INVOICE"
    align = 'R' if selected_theme != 'Minimal' else 'L'
    
    if selected_theme == 'Minimal': pdf.set_xy(120, 15)
    
    pdf.cell(0, 10, doc_type, ln=True, align=align)
    
    # ... (Rest of the logic remains similar but can be tweaked per theme)
    # For now, we will use the same 'Modern' body logic for all to test the switch
    
    pdf.ln(20)
    
    # [Insert the rest of the layout code from the previous working file here]
    # For brevity, I'm assuming we keep the table logic the same for now.
    
    # ... (Keep the rest of the generation logic) ...
    
    # --- SAVE FILE ---
    save_dir = os.path.join(current_app.static_folder, 'uploads', 'documents')
    os.makedirs(save_dir, exist_ok=True)
    file_path = os.path.join(save_dir, output_filename)
    
    pdf.output(file_path)
    return file_path