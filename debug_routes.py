from app import app

print("\n--- CHECKING ROUTES ---")
found = False
for rule in app.url_map.iter_rules():
    if "quote" in str(rule):
        print(f"✅ ACTIVE: {rule}  ->  {rule.endpoint}")
        found = True

if not found:
    print("❌ ERROR: The server cannot see ANY quote routes.")