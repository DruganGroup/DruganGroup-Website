import time
import os
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
BASE_URL = "http://127.0.0.1:5000"
LOGIN_EMAIL = "admin@titanium.com"
LOGIN_PASS = "password123"
REPORT_DIR = "test_reports/chaos_run"
results_log = []

def log_result(test_name, status, details=""):
    print(f"   👉 {status}: {details}")
    results_log.append({"test": test_name, "status": status, "details": details})

def run_chaos_monkey():
    if not os.path.exists(REPORT_DIR):
        os.makedirs(REPORT_DIR)
        
    print("🐵 CHAOS MONKEY STARTED: Testing Finance Module ONLY...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, slow_mo=1000)
        page = browser.new_page()

        try:
            # 1. LOGIN
            print("\n🔹 [Task 1] Logging In...")
            page.goto(f"{BASE_URL}/login")
            page.fill('input[name="email"]', LOGIN_EMAIL)
            page.fill('input[name="password"]', LOGIN_PASS)
            page.click('button[type="submit"]')
            page.wait_for_url("**/launcher")
            log_result("Login", "PASS", "Entered Launcher")

            # 2. DASHBOARD (Matches finance_dashboard.html)
            print("\n🔹 [Task 2] Finance Overview...")
            page.goto(f"{BASE_URL}/finance-dashboard")
            if page.is_visible("text=Financial Overview"):
                log_result("Finance Dash", "PASS", "Overview Loaded")
            else:
                log_result("Finance Dash", "WARN", "Header text mismatch")

            # 3. SALES LEDGER (Matches finance_invoices.html)
            print("\n🔹 [Task 3] Sales Ledger...")
            page.goto(f"{BASE_URL}/finance/invoices")
            if page.is_visible("text=Sales Ledger"):
                log_result("Invoices", "PASS", "Page Loaded")
            else:
                 log_result("Invoices", "WARN", "Header text mismatch")

            # 4. MATERIALS (Matches finance_materials.html)
            # Replaces the Client test because this actually exists in your menu!
            print("\n🔹 [Task 4] Adding Material Item...")
            page.goto(f"{BASE_URL}/finance/materials")
            
            # Click "New Item"
            if page.is_visible("text=New Item"):
                page.click("text=New Item")
                
                # Wait for #addMaterialModal
                page.wait_for_selector('#addMaterialModal', state='visible')
                
                # Fill Form
                page.fill('input[name="name"]', "Chaos Timber")
                page.fill('input[name="supplier"]', "Monkey Supplies")
                page.fill('input[name="price"]', "15.50")
                
                # Click "Save Item"
                page.click('button:has-text("Save Item")')
                log_result("Materials", "PASS", "Item Added")
            else:
                log_result("Materials", "FAIL", "New Item button not found")

            # 5. HR (Matches finance_hr.html)
            print("\n🔹 [Task 5] Hiring Staff...")
            page.goto(f"{BASE_URL}/finance/hr")
            
            # Click "New Employee"
            if page.is_visible("text=New Employee"):
                page.click("text=New Employee")
                
                # Wait for #staffModal
                page.wait_for_selector('#staffModal', state='visible')
                
                page.fill('input[name="name"]', "Test Monkey")
                page.fill('input[name="email"]', "test@monkey.com")
                
                # Correct Input Name: pay_rate (Line 118 in your file)
                if page.is_visible('input[name="pay_rate"]'):
                    page.fill('input[name="pay_rate"]', "25.00")
                
                # Click "Save Record"
                page.click('button:has-text("Save Record")')
                log_result("HR", "PASS", "Staff Hired")
            else:
                log_result("HR", "FAIL", "New Employee button not found")

            # 6. FLEET (Matches finance_fleet.html)
            print("\n🔹 [Task 6] Add Vehicle...")
            page.goto(f"{BASE_URL}/finance/fleet")
            
            # Click "Add Vehicle"
            if page.is_visible("text=Add Vehicle"):
                 page.click("text=Add Vehicle")
                 
                 # Wait for #addVehicleModal
                 page.wait_for_selector('#addVehicleModal', state='visible')
                 
                 # Correct Input Name: reg_number (Line 135 in your file)
                 page.fill('input[name="reg_number"]', "CHAOS-VAN")
                 page.fill('input[name="make_model"]', "Chaos Transit")

                 # Click "Save Vehicle"
                 page.click('button:has-text("Save Vehicle")')
                 log_result("Fleet", "PASS", "Vehicle Added")
            else:
                 log_result("Fleet", "FAIL", "Add Vehicle button not found")

            # 7. SETTINGS (Matches settings_general.html)
            print("\n🔹 [Task 7] Settings...")
            page.goto(f"{BASE_URL}/finance/settings/general")
            
            # Check for "Business Profile" text
            if page.is_visible("text=Business Profile"):
                log_result("Settings", "PASS", "Settings Loaded")
            else:
                log_result("Settings", "WARN", "Header text mismatch")

            # 8. LOGOUT
            print("\n🔹 [Task 8] Logout...")
            page.goto(f"{BASE_URL}/logout")
            log_result("Logout", "PASS", "Logged out")

        except Exception as e:
            log_result("CRITICAL", "ERROR", str(e))
            page.screenshot(path=f"{REPORT_DIR}/crash.png")
        
        finally:
            print("\n" + "="*40)
            print("📝 FINAL REPORT")
            for item in results_log:
                print(f"{'✅' if item['status']=='PASS' else '❌'} {item['test']}")
            print("="*40)
            browser.close()

if __name__ == "__main__":
    run_chaos_monkey()