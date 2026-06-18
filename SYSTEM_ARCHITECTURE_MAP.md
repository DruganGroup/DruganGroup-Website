# Business Better - System Architecture & Codebase Map

This document serves as a comprehensive map of the Business Better SaaS platform, outlining the directory structure, core modules, and business logic.

---

## 1. Core Application & Configuration
*(See `DATABASE_MAP.md` for a comprehensive schema breakdown of the PostgreSQL database)*
The root directory contains the foundational files that boot the application, manage the database, and define the environment.

- **`app.py`**: The main Flask application factory. Initializes the app, registers all Blueprints (routes), sets up error handlers, and configures the environment.
- **`db.py`**: Handles all PostgreSQL database connections and fetching the global site configuration for multi-tenancy.
- **`check_db.py` & `db_audit.py`**: Helper scripts for database schema validation, integrity checks, and debugging.
- **`Dockerfile` & `requirements.txt`**: Containerization and dependency definitions for deploying the app to platforms like Render.
- **`.env.example`**: Template for required environment variables (Database URLs, Stripe Keys, SMTP credentials).
- **`email_service.py`**: Centralized service for dispatching emails via SMTP.
- **`telematics_engine.py`**: Logic handling external telematics integrations or background vehicle tracking logic.

---

## 2. Routing Modules (`/routes`)
The application uses Flask Blueprints to organize routing logically by business domain.

### Authentication & Public
- **`auth_routes.py`**: Handles user login, registration, password resets, and the Stripe webhook integration for subscription payments. Includes the logic to provision a new tenant's database records.
- **`public_routes.py` & `publicbb.py`**: The frontend marketing site for Business Better (pricing pages, landing page, contact forms).

### Super Admin (Command Center)
- **`admin_routes.py`**: The Super Admin Command Center. Handles tenant management, BB Staff creation, global analytics, manual backups, data wiping, and the BB Helpdesk ticket logic.
- **`plans.py`**: Management of subscription tiers (Bronze, Silver, Gold), pricing, and feature limitations.

### Tenant Office Hub (Operations)
- **`office_routes.py`**: The main dashboard for tenant admins.
- **`client_routes.py`**: CRM functionality; managing clients and their physical properties/sites.
- **`quote_routes.py`**: Building, sending, and tracking estimates/quotes.
- **`job_routes.py`**: Scheduling jobs, assigning crews/vehicles, and tracking job statuses.
- **`pdf_routes.py`**: Routes that trigger the dynamic generation of PDF invoices, quotes, and reports.

### Tenant Finance & HR
- **`finance_routes.py`**: Managing overheads, materials, supplier costs, and tracking overall job profitability.
- **`transactions.py`**: In-depth transaction logging and invoice payment tracking.
- **`hr_routes.py`**: Staff management, leave tracking, and payroll calculations.

### Tenant Site Companion (Field Staff)
- **`site_routes.py`**: The mobile-friendly view for field workers to see assigned jobs, update statuses, and log defects. Includes the Clock-In/Clock-Out logic.
- **`compliance_routes.py`**: Generation and tracking of RAMS (Risk Assessments and Method Statements) and safety signatures.

### Tenant Client Portal
- **`portal_routes.py`**: The external-facing portal where a tenant's clients can log in to view their quotes, pay invoices, and submit service requests.

---

## 3. Microservices & Engines (`/services`)
Isolated Python modules that handle heavy lifting and third-party interactions.

- **`pdf_generator.py`**: The engine responsible for converting HTML templates and data into downloadable PDF files using libraries like `pdfkit` or `WeasyPrint`.
- **`imap_engine.py`**: Handles reading incoming emails (e.g., parsing replies to support tickets or automated invoice ingestion).
- **`tax_engine.py`**: Calculates VAT/Tax based on the tenant's configured country code and local tax laws.
- **`ai_assistant.py`**: Integration with OpenAI/LLMs to provide smart suggestions, draft emails, or analyze data.
- **`enforcement.py`**: Logic that checks tenant subscription limits (e.g., locking out users if they exceed their plan's max user limit).
- **`calculators/`**: Sub-directory for specific complex mathematical logic (e.g., profit margin calculators).

---

## 4. Utilities (`/utils`)
Helper functions used globally across the application.

- **`extensions.py`**: Initializes global extensions like `limiter` (rate-limiting to prevent brute force attacks).
- **`validators.py`**: Security functions to validate user input, sanitize table names, and prevent SQL injection.
- **`encryption.py`**: Helpers for hashing sensitive data beyond standard passwords.
- **`translations.py`**: Multi-language dictionary and functions to translate the UI based on the user's locale.
- **`certificates.py`**: Logic for generating compliance or training certificates.

---

## 5. User Interface & Views (`/templates`)
The frontend is built using Jinja2 HTML templates, styled with Bootstrap 5 and custom CSS.

- **`main_launcher.html`**: The portal screen users see immediately after logging in, allowing them to select an "App" (Office, Site, Finance) based on their RBAC permissions.
- **`error.html`**: Custom 404/500 error pages.

### Template Subdirectories
- **`/admin`**: The Super Admin Command Center interfaces (`super_admin.html`, `bb_support_dashboard.html`, `company_details.html`, etc.).
- **`/public` & `/publicbb`**: The public-facing website and marketing pages.
- **`/office`**: The tenant's office dashboard, job boards, and quote builders.
- **`/site`**: The mobile-optimized field worker interfaces.
- **`/finance`**: Dashboards for financial metrics, overheads, and settings.
- **`/hr`**: Staff lists, timesheets, and leave management UI.
- **`/portal`**: The end-client portal where customers pay invoices.
- **`/clients`**: CRM interfaces for managing customer data.
- **`/components`**: Reusable HTML snippets (navbars, footers, modals) included via Jinja `{% include %}`.
- **`/emails`**: HTML templates for outbound system emails (Welcome emails, invoices, password resets).

---

## 6. Static Assets (`/static`)
Publicly accessible files served directly to the browser.

- **`style.css`**: Global custom stylesheet.
- **`/images`**: Logos, icons, and placeholder avatars.
- **`/uploads`**: Directory where user-uploaded files (tenant logos, vehicle defect photos, compliance signatures) are securely stored.

---

## 7. Development Utilities
- **`check_db.py`**: Local development utility to audit database schema.
- **`factory_reset.py`**: Destructive script to drop and recreate database tables. Not used in production.
- **`generate_codebase_map.py`**: A utility script used to generate a map of the codebase.

---

## 8. Regional Certificates & Compliance Routing
The system dynamically routes and generates compliance certificates based on a company's country code. Rather than using the UK-specific CP12 and EICR certificates universally, the application will leverage native templates for relevant countries.

**Mapping Logic (`utils/certificates.py` & `routes/compliance_routes.py`)**:
- **Gas (CP12 Equivalents)**: `gas_cert` (Spain), `qualigaz` (France), `gas_dvgw` (Germany), `epa_energy` (USA).
- **Electrical (EICR Equivalents)**: `nfpa70e` (USA), `esa_defect` (Canada), `ccew` (Australia), `cie_elec` (Spain), `consuel` (France), `dguv_v3` (Germany), `dewa_elec` (UAE).
- When a regional certificate is generated and saved via `/office/cert/<country_code>/<cert_type>/save`, it intelligently updates the property's `gas_expiry` or `eicr_expiry` depending on the certificate class to ensure accurate compliance tracking.

---

## System Workflow Example: A Tenant Lifecycle
1. **Signup (`auth_routes.py`)**: User selects a plan on `/register`.
2. **Payment (`stripe_webhook`)**: Stripe processes payment, pings webhook, marking `subscriptions.status = Active`.
3. **Login (`main_launcher.html`)**: User logs in. RBAC determines what modules they can click.
4. **Operations (`office_routes.py`)**: Tenant creates jobs and schedules staff.
5. **Field Work (`site_routes.py`)**: Staff clocks in, drives vehicle (logging defects), and completes job.
6. **Billing (`pdf_routes.py`)**: Office generates an invoice PDF and emails it via `email_service.py`.
7. **Oversight (`admin_routes.py`)**: Super Admin views the tenant's usage metrics in the Command Center.
