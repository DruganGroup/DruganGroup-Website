import os
import re
import ast
from collections import defaultdict
import shutil

# Directories
ROUTES_DIR = 'routes'
TEMPLATES_DIR = 'templates'
OUTPUT_DIR = 'system_manual'

# Regex patterns for SQL
SQL_PATTERN = re.compile(r'SELECT\s+.*?\s+FROM\s+([a-zA-Z0-9_]+)', re.IGNORECASE)
INSERT_PATTERN = re.compile(r'INSERT\s+INTO\s+([a-zA-Z0-9_]+)', re.IGNORECASE)
UPDATE_PATTERN = re.compile(r'UPDATE\s+([a-zA-Z0-9_]+)\s+SET', re.IGNORECASE)
DELETE_PATTERN = re.compile(r'DELETE\s+FROM\s+([a-zA-Z0-9_]+)', re.IGNORECASE)
TEMPLATE_PATTERN = re.compile(r'render_template\([\'\"]([^\'\"]+)[\'\"]')

def parse_database_map():
    tables = {}
    current_table = None
    if not os.path.exists('DATABASE_MAP.md'):
        return tables
        
    with open('DATABASE_MAP.md', 'r', encoding='utf-8') as f:
        for line in f:
            t_match = re.match(r'##\s+Table:\s+`([^`]+)`', line)
            if t_match:
                current_table = t_match.group(1)
                tables[current_table] = []
                continue
            
            if current_table and line.startswith('|') and not line.startswith('|---') and not line.startswith('| Column Name'):
                parts = [p.strip() for p in line.split('|') if p.strip()]
                if len(parts) >= 4:
                    tables[current_table].append({
                        'name': parts[0],
                        'type': parts[1],
                        'length': parts[2],
                        'nullable': parts[3]
                    })
    return tables

def analyze_routes():
    # Map of table -> { 'reads': [{file, route, template}], 'writes': [{file, route, template}] }
    table_ops = defaultdict(lambda: {'reads': [], 'writes': []})
    # Map of template -> { 'reads': [table], 'writes': [table] }
    template_data = defaultdict(lambda: {'reads': set(), 'writes': set()})
    
    files_to_check = ['app.py']
    if os.path.exists(ROUTES_DIR):
        for root, _, files in os.walk(ROUTES_DIR):
            for f in files:
                if f.endswith('.py'):
                    files_to_check.append(os.path.join(root, f))
                    
    for path in files_to_check:
        if not os.path.exists(path):
            continue
            
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            
            try:
                tree = ast.parse(content)
                for node in tree.body:
                    if isinstance(node, ast.FunctionDef):
                        func_source = ast.get_source_segment(content, node)
                        if not func_source: continue
                        
                        # Find routes (decorators)
                        route_path = node.name
                        for decorator in node.decorator_list:
                            if isinstance(decorator, ast.Call) and getattr(decorator.func, 'id', '') in ['route', 'post', 'get']:
                                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                                    route_path = f"{route_path} ({decorator.args[0].value})"
                        
                        # Find SQL
                        reads = set(SQL_PATTERN.findall(func_source))
                        writes = set()
                        writes.update(INSERT_PATTERN.findall(func_source))
                        writes.update(UPDATE_PATTERN.findall(func_source))
                        writes.update(DELETE_PATTERN.findall(func_source))
                        
                        # Find templates
                        templates = TEMPLATE_PATTERN.findall(func_source)
                        
                        op_info = {
                            'file': path,
                            'route': route_path,
                            'templates': templates
                        }
                        
                        for table in reads:
                            table_ops[table.lower()]['reads'].append(op_info)
                            for t in templates:
                                template_data[t]['reads'].add(table.lower())
                                
                        for table in writes:
                            table_ops[table.lower()]['writes'].append(op_info)
                            for t in templates:
                                template_data[t]['writes'].add(table.lower())
                                
            except Exception as e:
                print(f"Failed to parse {path}: {e}")
                
    return table_ops, template_data

def generate_html(tables, table_ops, template_data):
    if os.path.exists(OUTPUT_DIR):
        shutil.rmtree(OUTPUT_DIR)
    os.makedirs(OUTPUT_DIR)
    
    # CSS
    css = """
    body { font-family: Arial, sans-serif; line-height: 1.6; max-width: 1200px; margin: 0 auto; padding: 20px; color: #333; }
    h1, h2, h3 { color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 10px; }
    a { color: #3498db; text-decoration: none; }
    a:hover { text-decoration: underline; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 20px; }
    th, td { text-align: left; padding: 12px; border: 1px solid #ddd; }
    th { background-color: #f8f9fa; }
    .nav { margin-bottom: 30px; background: #f8f9fa; padding: 15px; border-radius: 5px; }
    .badge { display: inline-block; padding: 3px 8px; border-radius: 3px; font-size: 0.85em; font-weight: bold; }
    .badge-read { background: #e8f4f8; color: #2980b9; }
    .badge-write { background: #fdf2e9; color: #d35400; }
    .container { display: flex; gap: 20px; }
    .sidebar { width: 250px; background: #f8f9fa; padding: 15px; border-radius: 5px; }
    .content { flex-grow: 1; }
    .card { background: #fff; border: 1px solid #ddd; border-radius: 5px; padding: 15px; margin-bottom: 15px; }
    """
    
    def write_page(filename, title, body_html):
        with open(os.path.join(OUTPUT_DIR, filename), 'w', encoding='utf-8') as f:
            f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{title}</title>
    <style>{css}</style>
</head>
<body>
    <div class="nav">
        <a href="index.html">Home</a> | 
        <a href="tables.html">Database Tables</a> | 
        <a href="pages.html">Pages & Templates</a>
    </div>
    <div class="container">
        <div class="content">
            {body_html}
        </div>
    </div>
</body>
</html>""")

    # Index Page
    index_html = f"""
    <h1>System Workshop Manual</h1>
    <p>Welcome to the interactive data flow and structure manual. This documentation shows exactly how data flows from the PostgreSQL database through the Python routes and into the HTML templates.</p>
    
    <div style="display: flex; gap: 20px;">
        <div class="card" style="flex: 1;">
            <h3>Database Tables ({len(tables)})</h3>
            <p>Explore all database tables, their columns, and which pages read or modify their data.</p>
            <a href="tables.html">View Tables &raquo;</a>
        </div>
        <div class="card" style="flex: 1;">
            <h3>Pages & Templates</h3>
            <p>Explore frontend pages, their routes, and which database tables they interact with.</p>
            <a href="pages.html">View Pages &raquo;</a>
        </div>
    </div>
    """
    write_page('index.html', 'System Workshop Manual', index_html)
    
    # Tables Index
    tables_html = "<h1>Database Tables</h1><ul>"
    for table in sorted(tables.keys()):
        tables_html += f"<li><a href='table_{table}.html'>{table}</a></li>"
    tables_html += "</ul>"
    write_page('tables.html', 'Database Tables', tables_html)
    
    # Individual Table Pages
    for table, columns in tables.items():
        t_html = f"<h1>Table: {table}</h1>"
        t_html += "<h2>Schema</h2>"
        t_html += "<table><tr><th>Column Name</th><th>Type</th><th>Max Length</th><th>Nullable</th></tr>"
        for col in columns:
            t_html += f"<tr><td>{col['name']}</td><td>{col['type']}</td><td>{col['length']}</td><td>{col['nullable']}</td></tr>"
        t_html += "</table>"
        
        ops = table_ops.get(table, {'reads': [], 'writes': []})
        
        t_html += "<h2>Data Flow</h2>"
        t_html += "<h3>Pages that Read from this Table</h3>"
        if ops['reads']:
            t_html += "<ul>"
            for op in ops['reads']:
                t_links = ", ".join([f"<a href='page_{t.replace('/', '_').replace('.', '_')}.html'>{t}</a>" for t in op['templates']])
                if not t_links: t_links = "<em>No template</em>"
                t_html += f"<li><strong>{op['route']}</strong> in <code>{op['file']}</code> &rarr; Renders: {t_links}</li>"
            t_html += "</ul>"
        else:
            t_html += "<p>No known read operations.</p>"
            
        t_html += "<h3>Pages that Modify this Table</h3>"
        if ops['writes']:
            t_html += "<ul>"
            for op in ops['writes']:
                t_links = ", ".join([f"<a href='page_{t.replace('/', '_').replace('.', '_')}.html'>{t}</a>" for t in op['templates']])
                if not t_links: t_links = "<em>No template (API/Redirect)</em>"
                t_html += f"<li><strong>{op['route']}</strong> in <code>{op['file']}</code> &rarr; Related Templates: {t_links}</li>"
            t_html += "</ul>"
        else:
            t_html += "<p>No known write operations.</p>"
            
        write_page(f'table_{table}.html', f'Table: {table}', t_html)
        
    # Pages Index
    pages_html = "<h1>Pages & Templates</h1>"
    pages_html += "<table><tr><th>Template</th><th>Reads Data From</th><th>Modifies Data In</th></tr>"
    for template in sorted(template_data.keys()):
        reads = ", ".join([f"<a href='table_{t}.html'>{t}</a>" for t in template_data[template]['reads']])
        writes = ", ".join([f"<a href='table_{t}.html'>{t}</a>" for t in template_data[template]['writes']])
        t_id = template.replace('/', '_').replace('.', '_')
        pages_html += f"<tr><td><a href='page_{t_id}.html'>{template}</a></td><td>{reads}</td><td>{writes}</td></tr>"
    pages_html += "</table>"
    write_page('pages.html', 'Pages & Templates', pages_html)
    
    # Individual Template Pages
    for template, data in template_data.items():
        t_id = template.replace('/', '_').replace('.', '_')
        p_html = f"<h1>Template: {template}</h1>"
        
        p_html += "<h2>Database Interactions</h2>"
        p_html += "<h3>Reads from Tables:</h3><ul>"
        for t in data['reads']:
            p_html += f"<li><a href='table_{t}.html'>{t}</a></li>"
        if not data['reads']: p_html += "<li>None</li>"
        p_html += "</ul>"
        
        p_html += "<h3>Modifies Tables:</h3><ul>"
        for t in data['writes']:
            p_html += f"<li><a href='table_{t}.html'>{t}</a></li>"
        if not data['writes']: p_html += "<li>None</li>"
        p_html += "</ul>"
        
        write_page(f'page_{t_id}.html', f'Page: {template}', p_html)

if __name__ == '__main__':
    print("Parsing database schema...")
    tables = parse_database_map()
    print(f"Found {len(tables)} tables.")
    
    print("Analyzing routes and data flow...")
    table_ops, template_data = analyze_routes()
    
    print("Generating HTML workshop manual...")
    generate_html(tables, table_ops, template_data)
    
    print("Done! Open system_manual/index.html in your browser.")
