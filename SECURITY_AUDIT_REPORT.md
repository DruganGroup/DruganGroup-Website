# Security & Code Quality Audit Report
**DruganGroup Website - Business Better Platform**  
**Date:** June 10, 2026  
**Auditor:** Cline AI Assistant

---

## Executive Summary

This comprehensive audit identified **12 security issues** and **8 code quality concerns** across the DruganGroup Website codebase. Issues range from **CRITICAL** (hardcoded credentials) to **LOW** (missing version pins in dependencies).

### Risk Summary
- 🔴 **CRITICAL**: 1 issue
- 🟠 **HIGH**: 4 issues  
- 🟡 **MEDIUM**: 7 issues
- 🟢 **LOW**: 8 issues

---

## 🔴 CRITICAL ISSUES

### 1. Hardcoded Database Password
**File:** `db.py` (Line 26)  
**Severity:** CRITICAL  
**Description:** PostgreSQL password is hardcoded in plain text.

```python
password="admin123",
```

**Risk:** If this code is committed to a public repository or accessed by unauthorized users, the database can be compromised.

**Recommendation:**
```python
# Use environment variables
password=os.environ.get("DB_PASSWORD", ""),
```

Add to `.env` file (and ensure `.env` is in `.gitignore`):
```
DB_PASSWORD=your_secure_password_here
```

---

## 🟠 HIGH SEVERITY ISSUES

### 2. SQL Injection Vulnerabilities (Multiple Locations)
**Files:** `routes/admin_routes.py`, `routes/plans.py`  
**Severity:** HIGH  
**Description:** Dynamic table names in SQL queries using f-strings without proper validation.

**Vulnerable Code Examples:**
```python
# admin_routes.py (Line 45)
cur.execute(f"SELECT COUNT(*) FROM {t} WHERE company_id = %s", (company_id,))

# admin_routes.py (Line 52)
cur.execute(f"SELECT to_regclass('{table}')")

# admin_routes.py (Line 56)
cur.execute(f"SELECT * FROM {table} WHERE company_id = %s", (company_id,))

# plans.py (Line 89)
cur.execute(f"DELETE FROM {table}")
```

**Risk:** Attackers could manipulate table names to execute arbitrary SQL commands.

**Recommendation:**
```python
# Use a whitelist of allowed table names
ALLOWED_TABLES = ['companies', 'users', 'invoices', 'vehicles', 'jobs']

def validate_table_name(table):
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Invalid table name: {table}")
    return table

# Then use:
table = validate_table_name(table)
cur.execute(f"SELECT COUNT(*) FROM {table} WHERE company_id = %s", (company_id,))
```

### 3. Weak Secret Key in Development
**File:** `app.py` (Line 34)  
**Severity:** HIGH  
**Description:** Fallback secret key is predictable.

```python
app.secret_key = os.environ.get("SECRET_KEY", "dev_key_123")
```

**Risk:** If `SECRET_KEY` environment variable is not set in production, sessions can be hijacked.

**Recommendation:**
```python
app.secret_key = os.environ.get("SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("SECRET_KEY environment variable must be set!")
```

### 4. Missing CSRF Protection on Some Routes
**File:** Various route files  
**Severity:** HIGH  
**Description:** While CSRF protection is initialized, some POST routes may not be properly protected.

**Recommendation:**
- Audit all POST/PUT/DELETE routes to ensure CSRF tokens are validated
- Add `@csrf.exempt` decorator only where absolutely necessary (e.g., API endpoints)
- Ensure all forms include `{{ csrf_token() }}` in templates

### 5. No Rate Limiting
**Files:** All route files  
**Severity:** HIGH  
**Description:** No rate limiting on authentication endpoints or API routes.

**Risk:** Vulnerable to brute force attacks, DDoS, and credential stuffing.

**Recommendation:**
```python
# Install Flask-Limiter
pip install Flask-Limiter

# In app.py
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# On sensitive routes
@auth_bp.route('/login', methods=['POST'])
@limiter.limit("5 per minute")
def login():
    # ...
```

---

## 🟡 MEDIUM SEVERITY ISSUES

### 6. Missing Input Validation
**Files:** Multiple route files  
**Severity:** MEDIUM  
**Description:** User inputs are not consistently validated before database operations.

**Recommendation:**
- Implement input validation using Flask-WTF forms or Pydantic
- Validate email formats, phone numbers, dates, etc.
- Sanitize file uploads

### 7. Error Messages Expose Internal Information
**Files:** Multiple files  
**Severity:** MEDIUM  
**Description:** Error messages print stack traces and database errors to console.

```python
print(f"❌ DB Connection Error: {e}")
```

**Recommendation:**
- Use proper logging instead of print statements
- Don't expose detailed error messages to end users
- Log errors to a secure location

```python
import logging
logger = logging.getLogger(__name__)

try:
    # database operation
except Exception as e:
    logger.error(f"Database error: {str(e)}", exc_info=True)
    return "An error occurred", 500
```

### 8. Session Configuration Issues
**File:** `app.py` (Lines 38-41)  
**Severity:** MEDIUM  
**Description:** Session cookies set to `Secure=True` but may break local development.

```python
app.config['SESSION_COOKIE_SECURE'] = True  # Requires HTTPS
```

**Recommendation:**
```python
# Make it environment-dependent
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'
```

### 9. No Password Complexity Requirements
**Files:** `routes/auth_routes.py`  
**Severity:** MEDIUM  
**Description:** No validation for password strength during signup.

**Recommendation:**
```python
import re

def validate_password(password):
    if len(password) < 8:
        return False, "Password must be at least 8 characters"
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain uppercase letter"
    if not re.search(r"[a-z]", password):
        return False, "Password must contain lowercase letter"
    if not re.search(r"\d", password):
        return False, "Password must contain a number"
    return True, "Valid"
```

### 10. File Upload Security
**File:** `db.py` (Lines 14, 66-67)  
**Severity:** MEDIUM  
**Description:** File upload validation only checks extensions, not content.

**Recommendation:**
```python
import magic  # python-magic library

def validate_file_content(file):
    # Check actual file type, not just extension
    file_type = magic.from_buffer(file.read(1024), mime=True)
    file.seek(0)  # Reset file pointer
    
    allowed_types = ['image/png', 'image/jpeg', 'image/gif']
    return file_type in allowed_types
```

### 11. Missing HTTP Security Headers
**File:** `app.py`  
**Severity:** MEDIUM  
**Description:** No security headers configured (CSP, X-Frame-Options, etc.)

**Recommendation:**
```python
@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Content-Security-Policy'] = "default-src 'self'"
    return response
```

### 12. Subdomain Validation Weakness
**File:** `app.py` (Lines 76-97)  
**Severity:** MEDIUM  
**Description:** Subdomain extraction could be exploited with malformed hostnames.

**Recommendation:**
```python
import re

def extract_subdomain(host, base_domain):
    # Validate hostname format
    if not re.match(r'^[a-z0-9-]+\.' + re.escape(base_domain) + '$', host):
        return None
    return host.replace(f'.{base_domain}', '').split('.')[0]
```

---

## 🟢 LOW SEVERITY ISSUES

### 13. Missing Dependency Version Pins
**File:** `requirements.txt`  
**Severity:** LOW  
**Description:** Most dependencies don't have version pins.

```txt
Flask  # Should be Flask==3.0.0
psycopg2-binary  # Should specify version
```

**Recommendation:**
```bash
pip freeze > requirements.txt
```

### 14. No Database Connection Pooling
**File:** `db.py`  
**Severity:** LOW  
**Description:** Each request creates a new database connection.

**Recommendation:**
```python
from psycopg2 import pool

connection_pool = pool.SimpleConnectionPool(1, 20, **db_config)

def get_db():
    return connection_pool.getconn()

def return_db(conn):
    connection_pool.putconn(conn)
```

### 15. Missing API Documentation
**Severity:** LOW  
**Description:** No OpenAPI/Swagger documentation for API endpoints.

### 16. No Automated Security Scanning
**Severity:** LOW  
**Recommendation:** Add GitHub Actions workflow:
```yaml
- name: Security Scan
  run: |
    pip install bandit safety
    bandit -r . -f json -o bandit-report.json
    safety check
```

### 17. Template Syntax Fixed
**File:** `templates/publicbb/help.html`  
**Severity:** LOW  
**Status:** ✅ FIXED  
**Description:** Duplicate `{% endblock %}` tag removed. Grid layout changed from horizontal to vertical.

### 18. Missing Logging Configuration
**Severity:** LOW  
**Description:** No centralized logging configuration.

**Recommendation:**
```python
import logging
from logging.handlers import RotatingFileHandler

if not app.debug:
    file_handler = RotatingFileHandler('logs/app.log', maxBytes=10240, backupCount=10)
    file_handler.setFormatter(logging.Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
```

### 19. No Database Migration System
**Severity:** LOW  
**Description:** Schema changes are done manually.

**Recommendation:**
```bash
pip install Flask-Migrate
```

### 20. Missing Health Check Endpoint
**Severity:** LOW  
**Recommendation:**
```python
@app.route('/health')
def health_check():
    return {'status': 'healthy', 'database': 'connected'}, 200
```

---

## Code Quality Issues

### 1. Inconsistent Error Handling
- Some functions return None on error, others raise exceptions
- Mix of try/except patterns

### 2. Code Duplication
- Database connection logic repeated across routes
- Similar validation logic in multiple places

### 3. Missing Type Hints
- No type annotations on function parameters/returns

### 4. Long Functions
- Some route handlers exceed 100 lines
- Should be refactored into smaller functions

### 5. Magic Numbers
- Hardcoded values like `12` (hours), `5432` (port) should be constants

### 6. Commented Out Code
- Dead code should be removed, not commented

### 7. Missing Docstrings
- Many functions lack documentation

### 8. Inconsistent Naming
- Mix of camelCase and snake_case in some places

---

## Immediate Action Items (Priority Order)

1. **🔴 CRITICAL:** Move hardcoded password to environment variable
2. **🟠 HIGH:** Fix SQL injection vulnerabilities with table name validation
3. **🟠 HIGH:** Enforce SECRET_KEY requirement in production
4. **🟠 HIGH:** Add rate limiting to authentication endpoints
5. **🟡 MEDIUM:** Implement proper error logging
6. **🟡 MEDIUM:** Add security headers
7. **🟡 MEDIUM:** Validate password complexity
8. **🟢 LOW:** Pin dependency versions

---

## Positive Security Findings ✅

1. ✅ CSRF protection is initialized
2. ✅ Session cookies use HttpOnly and SameSite
3. ✅ Database uses parameterized queries (mostly)
4. ✅ Environment variables used for sensitive config (DATABASE_URL)
5. ✅ SSL/TLS enforced for database connections
6. ✅ File upload extensions are validated
7. ✅ Session timeout configured (12 hours)

---

## Compliance Notes

- **GDPR:** Ensure user data deletion capabilities exist
- **PCI DSS:** If handling payments, ensure Stripe integration follows best practices
- **Data Retention:** Implement data retention policies

---

## Recommended Tools

1. **Bandit** - Python security linter
2. **Safety** - Dependency vulnerability scanner
3. **Snyk** - Continuous security monitoring
4. **OWASP ZAP** - Web application security scanner
5. **SonarQube** - Code quality analysis

---

## Conclusion

The application has a solid foundation with CSRF protection and secure session management. However, **immediate action is required** to address the hardcoded credentials and SQL injection vulnerabilities. Implementing the recommended fixes will significantly improve the security posture of the platform.

**Estimated Remediation Time:** 8-16 hours for critical/high issues

---

*End of Report*
