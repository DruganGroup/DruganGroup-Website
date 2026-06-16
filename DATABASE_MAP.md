# Business Better - Database Architecture Map

This document outlines the PostgreSQL database schema for the Business Better platform, which supports multi-tenancy, subscription billing, operations, and HR management.

## 1. Core Platform & Multi-Tenancy

### `companies` (Tenants)
The core tenant table. Each registered business gets one row here.
- `id` (SERIAL PRIMARY KEY)
- `name` (VARCHAR) - Business Name
- `sub_domain` (VARCHAR) - Subdomain for White Label portal (e.g. `drugangroup`)
- `contact_email` (VARCHAR)
- `partner_code` (VARCHAR) - Referral/Partner tracking

### `users`
System users who can log in. Users belong to a company unless they are SuperAdmins.
- `id` (SERIAL PRIMARY KEY)
- `company_id` (INTEGER, FK to companies, NULLable for SuperAdmin)
- `name` (VARCHAR)
- `email` (VARCHAR UNIQUE)
- `password_hash` (VARCHAR)
- `role` (VARCHAR) - e.g., 'SuperAdmin', 'Admin', 'User'

### `plans` & `subscriptions`
Billing and subscription management via Stripe.
- **`plans`**: Details of available tiers (Bronze, Silver, Gold, Founder), including `price`, `max_users`, `max_vehicles`, `modules_enabled`, and `stripe_price_id`.
- **`subscriptions`**: The active subscription for a company, tracking `status`, `plan_id`, and quota limits.

### `settings` & `system_settings`
- **`settings`**: Tenant-specific configuration (e.g., `brand_color`, `logo`, `company_name`, `system_language`, `currency_symbol`).
- **`system_settings`**: Global configuration (e.g., `global_alert`).

## 2. HR & Staff

### `staff`
Employees of a tenant.
- `id` (SERIAL PRIMARY KEY)
- `company_id` (INTEGER)
- `name` (VARCHAR)
- `email` (VARCHAR)
- `position` (VARCHAR)
- `status` (VARCHAR) - e.g., 'Active'
- `pay_rate` (DECIMAL)

### `staff_leave`
Tracks holidays and absences.

## 3. Operations & Field (Site/Fleet)

### `jobs` / `quotes`
- Deals with estimates, assigned work, and status tracking.

### `vehicles` & `maintenance_logs`
- Fleet management. `maintenance_logs` tracks repairs, cost, and dates per vehicle.

## 4. Financials

### `overhead_categories` & `overhead_items`
- Tracks fixed business costs (Rent, Insurance) for accurate profit margin calculations.
- Items link to Categories via `category_id`.

### `suppliers` & `materials`
- Tracks supplier costs.

## 5. Support & Auditing

### `bb_support_tickets` & `bb_ticket_messages`
- Built-in helpdesk for tenants to contact Business Better SuperAdmins.

### `audit_logs` & `system_logs`
- **`audit_logs`**: Tracks admin actions.
- **`system_logs`**: Captures application errors, tracebacks, IP addresses, and routes for debugging.

---

## Render Server Database Specifics

The production database is a managed PostgreSQL instance hosted on Render.
- **Connection**: Managed via the `DATABASE_URL` environment variable.
- **SSL**: `sslmode=require` is explicitly set in `db.py` to ensure secure connections.
- **Migrations/Resets**: Can be performed via `check_db.py` (auditing) and `factory_reset.py` (WARNING: This truncates all base tables).

*Note: As new modules are built, ensure `FACTORY_RESET` scripts and this map are updated accordingly.*
