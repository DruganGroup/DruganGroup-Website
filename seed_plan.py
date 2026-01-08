from db import get_db
from app import app
import json

def seed_plans():
    print("💎 Seeding Plan Definitions...")
    with app.app_context():
        conn = get_db()
        cur = conn.cursor()
        
        try:
            # 1. Ensure we can enforce unique names (avoids duplicates)
            try:
                cur.execute("ALTER TABLE plans ADD CONSTRAINT unique_plan_name UNIQUE (name);")
                conn.commit()
            except:
                conn.rollback() # Constraint likely already exists, which is fine

            # 2. Define the Plans & Limits
            plans = [
                {
                    'name': 'Starter', 
                    'price': 29.99, 
                    'max_users': 2, 
                    'max_vehicles': 1,   # <--- The limit we are testing!
                    'max_clients': 5, 
                    'max_properties': 5, 
                    'max_storage': 100,
                    'modules': json.dumps(['Finance', 'Fleet'])
                },
                {
                    'name': 'Pro', 
                    'price': 79.99, 
                    'max_users': 10, 
                    'max_vehicles': 5, 
                    'max_clients': 50, 
                    'max_properties': 50, 
                    'max_storage': 1000,
                    'modules': json.dumps(['Finance', 'Fleet', 'HR', 'Compliance'])
                },
                {
                    'name': 'Enterprise Gold', 
                    'price': 199.99, 
                    'max_users': 100, 
                    'max_vehicles': 100, 
                    'max_clients': 500, 
                    'max_properties': 500, 
                    'max_storage': 10000,
                    'modules': json.dumps(['Finance', 'Fleet', 'HR', 'Compliance', 'ServiceDesk', 'Portal'])
                }
            ]

            # 3. Insert them into the database
            print("   - Inserting Plans...")
            for p in plans:
                cur.execute("""
                    INSERT INTO plans (name, price, max_users, max_vehicles, max_clients, max_properties, max_storage, modules_enabled)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE 
                    SET max_vehicles = EXCLUDED.max_vehicles, 
                        max_users = EXCLUDED.max_users,
                        modules_enabled = EXCLUDED.modules_enabled;
                """, (p['name'], p['price'], p['max_users'], p['max_vehicles'], p['max_clients'], p['max_properties'], p['max_storage'], p['modules']))
            
            conn.commit()
            print("✅ Plans defined successfully.")
            
        except Exception as e:
            conn.rollback()
            print(f"❌ Error: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    seed_plans()