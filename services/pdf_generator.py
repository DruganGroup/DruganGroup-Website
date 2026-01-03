import os
from weasyprint import HTML
from flask import render_template, current_app

def generate_pdf(template_name, context, output_filename):
    """
    Renders an HTML template into a PDF file.
    
    :param template_name: The HTML file in templates/ (e.g. 'office/pdf_quote.html')
    :param context: Dictionary of data to pass to the template (quote, company, etc.)
    :param output_filename: The name of the file to save (e.g. 'Quote_101.pdf')
    :return: The full path to the generated PDF.
    """
    
    # 1. Render the HTML with the data
    html_content = render_template(template_name, **context)
    
    # 2. Define Save Path (Use the static/uploads folder)
    # We create a specific 'invoices' folder to keep things tidy
    save_dir = os.path.join(current_app.static_folder, 'uploads', 'documents')
    os.makedirs(save_dir, exist_ok=True)
    
    file_path = os.path.join(save_dir, output_filename)
    
    # 3. Generate PDF
    # We set base_url so WeasyPrint can find your images/logos
    HTML(string=html_content, base_url=current_app.static_folder).write_pdf(file_path)
    
    return file_path