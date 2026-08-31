# build_all.py - Complete Publicbb Modernization Generator
import os

TEMPLATES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates', 'publicbb')

def save_template(filename, content):
    path = os.path.join(TEMPLATES_DIR, filename)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content.strip() + '\n')
    print(f"[OK] Generated: {filename}")

if __name__ == '__main__':
    print("Ready to generate templates...")
