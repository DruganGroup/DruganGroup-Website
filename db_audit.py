import os
import re
import ast

def find_files(directory, extension):
    matches = []
    for root, dirnames, filenames in os.walk(directory):
        for filename in filenames:
            if filename.endswith(extension):
                matches.append(os.path.join(root, filename))
    return matches

py_files = find_files('routes', '.py') + find_files('services', '.py') + ['app.py', 'db.py']

print("--- SQL INJECTION AUDIT ---")
sql_injection_pattern = re.compile(r"cur\.execute\(\s*[f]\"[^\"]*\{.*?\}")
for f in py_files:
    if not os.path.exists(f): continue
    with open(f, 'r', encoding='utf-8', errors='ignore') as file:
        content = file.readlines()
        for i, line in enumerate(content):
            if 'cur.execute(' in line and ('f"' in line or "f'" in line or "%" in line and not "(%" in line):
                # Only flag if it looks like dynamic formatting inside the SQL
                if re.search(r"f['\"].*?\{", line) or re.search(r"['\"].*?%.*?%[^s]", line):
                    # Exclude the ALLOWED_TABLES whitelist check which is safe
                    if "ALLOWED_TABLES" not in line and "{t}" not in line:
                        print(f"Potential SQL Injection in {f}:{i+1} -> {line.strip()}")

print("\n--- SYNTAX AUDIT ---")
for f in py_files:
    if not os.path.exists(f): continue
    with open(f, 'r', encoding='utf-8', errors='ignore') as file:
        try:
            ast.parse(file.read(), filename=f)
        except SyntaxError as e:
            print(f"Syntax error in {f}: {e}")
