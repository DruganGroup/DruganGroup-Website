import os
import glob

files_to_check = ['app.py'] + glob.glob('routes/*.py') + glob.glob('services/*.py')

for filepath in files_to_check:
    if not os.path.exists(filepath):
        continue
    
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Replace conn.close() with pass
    # We use pass to avoid IndentationError or SyntaxError in single-line statements
    new_content = content.replace('conn.close()', 'pass')

    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        print(f"Fixed {filepath}")
