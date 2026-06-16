from db import get_db
from werkzeug.security import generate_password_hash

conn = get_db()
if conn:
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email='nathan@businessbetter.co.uk'")
    u = cur.fetchone()
    pw = generate_password_hash('PassAdmin1234!')
    if u:
        cur.execute("UPDATE users SET password_hash=%s, role='SuperAdmin', company_id=NULL WHERE id=%s", (pw, u[0]))
    else:
        cur.execute("INSERT INTO users (company_id, name, email, password_hash, role) VALUES (NULL, 'Nathan Drugan', 'nathan@businessbetter.co.uk', %s, 'SuperAdmin')", (pw,))
    conn.commit()
    conn.close()
    print("Super Admin ensured.")
else:
    print("No DB connection")
