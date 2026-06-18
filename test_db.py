import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()
print("Connecting...")
try:
    conn = psycopg2.connect(os.environ['DATABASE_URL'], sslmode='require')
    print("Success!")
except Exception as e:
    print("Error:", e)
