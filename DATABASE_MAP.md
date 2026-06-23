# Database Schema Map

## Table: `bb_support_tickets`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| tenant_id | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| id | integer | None | NO |
| status | character varying | 50 | YES |
| description | text | None | YES |
| assigned_to | character varying | 100 | YES |
| company_name | character varying | 255 | YES |
| subject | character varying | 255 | YES |

## Table: `request_updates`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| request_id | integer | None | YES |
| is_public | boolean | None | YES |
| created_at | timestamp without time zone | None | YES |
| message | text | None | NO |
| author | character varying | 100 | YES |

## Table: `staff_leave`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| created_at | timestamp without time zone | None | YES |
| company_id | integer | None | YES |
| staff_id | integer | None | YES |
| start_date | date | None | YES |
| end_date | date | None | YES |
| id | integer | None | NO |
| status | character varying | 50 | YES |
| reason | character varying | 100 | YES |

## Table: `site_diary`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| job_id | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| staff_name | text | None | YES |
| entry_text | text | None | YES |

## Table: `bb_ticket_messages`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| ticket_id | integer | None | YES |
| sender_id | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| sender_type | character varying | 50 | YES |
| message | text | None | YES |

## Table: `job_rams`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| job_id | integer | None | YES |
| company_id | integer | None | YES |
| hazards | jsonb | None | YES |
| ppe | jsonb | None | YES |
| created_at | timestamp without time zone | None | YES |
| risk_level | character varying | 20 | YES |
| pdf_path | text | None | YES |
| method_statement | text | None | YES |

## Table: `company_partners`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | YES |
| partner_id | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| status | character varying | 20 | YES |

## Table: `banned_ips`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| banned_at | timestamp without time zone | None | YES |
| ip_address | text | None | NO |
| reason | text | None | YES |

## Table: `system_settings`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| key | text | None | NO |
| value | text | None | YES |

## Table: `plugin_licenses`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| date_added | timestamp without time zone | None | YES |
| plugin_id | text | None | YES |
| license_key | text | None | YES |

## Table: `subscriptions`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | YES |
| max_vehicles | integer | None | YES |
| max_clients | integer | None | YES |
| max_properties | integer | None | YES |
| max_storage | integer | None | YES |
| start_date | timestamp without time zone | None | YES |
| renewal_date | timestamp without time zone | None | YES |
| is_auto_renew | integer | None | YES |
| plan_id | integer | None | YES |
| max_users | integer | None | YES |
| plan_tier | text | None | YES |
| status | text | None | YES |
| stripe_customer_id | text | None | YES |
| modules | text | None | YES |

## Table: `modules`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| is_active | integer | None | YES |
| id | text | None | NO |
| name | text | None | YES |
| version | text | None | YES |

## Table: `vehicle_crews`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | NO |
| vehicle_id | integer | None | NO |
| staff_id | integer | None | NO |
| created_at | timestamp without time zone | None | YES |

## Table: `job_expenses`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| job_id | integer | None | YES |
| company_id | integer | None | YES |
| date | date | None | YES |
| cost | real | None | YES |
| created_at | timestamp without time zone | None | YES |
| description | text | None | YES |
| receipt_path | text | None | YES |

## Table: `invoices`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| quote_id | integer | None | YES |
| company_id | integer | None | NO |
| client_id | integer | None | NO |
| subtotal | numeric | None | YES |
| tax | numeric | None | YES |
| job_id | integer | None | YES |
| date_created | date | None | YES |
| total_amount | numeric | None | YES |
| id | integer | None | NO |
| date | date | None | YES |
| total | numeric | None | YES |
| created_at | timestamp without time zone | None | YES |
| due_date | date | None | YES |
| reference | character varying | 50 | YES |
| ref | character varying | 50 | YES |
| quote_ref | text | None | YES |
| status | character varying | 20 | YES |
| file_path | text | None | YES |
| notes | text | None | YES |

## Table: `invoice_items`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| invoice_id | integer | None | YES |
| quantity | numeric | None | YES |
| unit_price | numeric | None | YES |
| total | numeric | None | YES |
| description | text | None | YES |

## Table: `jobs`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| client_id | integer | None | YES |
| created_date | date | None | YES |
| company_id | integer | None | YES |
| staff_id | integer | None | YES |
| property_id | integer | None | YES |
| engineer_id | integer | None | YES |
| end_date | timestamp without time zone | None | YES |
| quote_id | integer | None | YES |
| sub_contractor_cost | numeric | None | YES |
| vehicle_id | integer | None | YES |
| quote_total | numeric | None | YES |
| estimated_days | integer | None | YES |
| duration_days | integer | None | YES |
| total_price | real | None | YES |
| deposit_amount | real | None | YES |
| created_at | timestamp without time zone | None | YES |
| site_lat | real | None | YES |
| site_lon | real | None | YES |
| site_address | text | None | YES |
| description | text | None | YES |
| status | text | None | YES |
| start_date | text | None | YES |
| invoice_date | text | None | YES |
| due_date | text | None | YES |
| ref | text | None | YES |
| display_ref | text | None | YES |
| private_notes | text | None | YES |
| work_summary | text | None | YES |
| client_signature | text | None | YES |

## Table: `quote_items`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| quote_id | integer | None | YES |
| quantity | numeric | None | YES |
| unit_price | numeric | None | YES |
| total | numeric | None | YES |
| description | text | None | YES |

## Table: `service_requests`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| property_id | integer | None | YES |
| client_id | integer | None | YES |
| company_id | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| partner_company_id | integer | None | YES |
| parent_request_id | integer | None | YES |
| partner_address_snapshot | character varying | 255 | YES |
| image_url | text | None | YES |
| priority | character varying | 50 | YES |
| photo_path | text | None | YES |
| issue_description | text | None | YES |
| severity | text | None | YES |
| status | text | None | YES |

## Table: `clients`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| is_active | integer | None | YES |
| company_id | integer | None | YES |
| portal_access | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| id | integer | None | NO |
| notes | text | None | YES |
| password_hash | text | None | YES |
| site_address | text | None | YES |
| gate_code | text | None | YES |
| billing_address | text | None | YES |
| status | text | None | YES |
| internal_notes | text | None | YES |
| name | text | None | YES |
| address | text | None | YES |
| phone | text | None | YES |
| email | text | None | YES |

## Table: `client_notifications`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| job_id | integer | None | YES |
| client_id | integer | None | YES |
| sent_at | timestamp without time zone | None | YES |
| message | text | None | YES |
| status | text | None | YES |

## Table: `staff_timesheets`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| staff_id | integer | None | YES |
| company_id | integer | None | YES |
| clock_in | timestamp without time zone | None | YES |
| clock_out | timestamp without time zone | None | YES |
| date | date | None | YES |
| total_hours | numeric | None | YES |
| job_id | integer | None | YES |
| status | character varying | 50 | YES |

## Table: `job_materials`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| quantity | integer | None | YES |
| job_id | integer | None | YES |
| date_added | timestamp without time zone | None | YES |
| id | integer | None | NO |
| unit_price | numeric | None | YES |
| added_at | timestamp without time zone | None | YES |
| description | character varying | 255 | NO |
| cost_price | numeric | None | YES |

## Table: `staff`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| pay_rate | real | None | YES |
| is_active | integer | None | YES |
| company_id | integer | None | YES |
| tax_limit | numeric | None | YES |
| ni_limit | numeric | None | YES |
| holiday_entitled | boolean | None | YES |
| cis_rate | numeric | None | YES |
| utr_number | character varying | 20 | YES |
| access_level | text | None | YES |
| bank_name | character varying | 100 | YES |
| account_number | character varying | 20 | YES |
| address | text | None | YES |
| employment_type | text | None | YES |
| tax_id | text | None | YES |
| role | character varying | 50 | YES |
| status | character varying | 20 | YES |
| license_path | text | None | YES |
| next_of_kin_name | text | None | YES |
| next_of_kin_phone | text | None | YES |
| nok_name | character varying | 100 | YES |
| nok_phone | character varying | 50 | YES |
| nok_relationship | character varying | 50 | YES |
| nok_address | text | None | YES |
| driving_license | text | None | YES |
| profile_photo | text | None | YES |
| sort_code | character varying | 20 | YES |
| tax_code | character varying | 20 | YES |
| name | text | None | YES |
| dept | text | None | YES |
| position | text | None | YES |
| email | text | None | YES |
| phone | text | None | YES |
| staff_type | text | None | YES |
| pay_model | text | None | YES |

## Table: `materials`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | YES |
| cost_price | numeric | None | YES |
| supplier_id | integer | None | YES |
| category | text | None | YES |
| unit | text | None | YES |
| supplier | text | None | YES |
| sku | text | None | YES |
| name | text | None | YES |

## Table: `overhead_categories`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | NO |
| created_at | timestamp without time zone | None | YES |
| name | character varying | 100 | NO |

## Table: `system_logs`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| status_code | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| company_id | integer | None | YES |
| user_id | integer | None | YES |
| id | integer | None | NO |
| ip_address | text | None | YES |
| level | character varying | 20 | YES |
| message | text | None | YES |
| traceback | text | None | YES |
| route | character varying | 100 | YES |

## Table: `audit_logs`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| created_at | timestamp without time zone | None | YES |
| company_id | integer | None | YES |
| target | character varying | 255 | YES |
| details | text | None | YES |
| ip_address | character varying | 50 | YES |
| admin_email | character varying | 150 | YES |
| action | character varying | 100 | YES |

## Table: `settings`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| company_id | integer | None | NO |
| key | text | None | NO |
| value | text | None | YES |

## Table: `companies`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| created_at | timestamp without time zone | None | YES |
| id | integer | None | NO |
| sub_domain | text | None | YES |
| contact_email | text | None | YES |
| phone | text | None | YES |
| subdomain | text | None | YES |
| partner_code | character varying | 20 | YES |
| name | text | None | NO |

## Table: `staff_attendance`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | YES |
| staff_id | integer | None | YES |
| date | date | None | YES |
| clock_in | timestamp without time zone | None | YES |
| clock_out | timestamp without time zone | None | YES |
| total_hours | numeric | None | YES |
| created_at | timestamp without time zone | None | YES |
| status | character varying | 50 | YES |
| notes | text | None | YES |

## Table: `quotes`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| property_id | integer | None | YES |
| company_id | integer | None | YES |
| client_id | integer | None | YES |
| date | date | None | YES |
| created_at | timestamp without time zone | None | YES |
| expiry_date | date | None | YES |
| estimated_days | numeric | None | YES |
| preferred_vehicle_id | integer | None | YES |
| id | integer | None | NO |
| subtotal | numeric | None | YES |
| tax | numeric | None | YES |
| total | numeric | None | YES |
| reference | text | None | YES |
| status | text | None | YES |
| notes | text | None | YES |
| job_title | text | None | YES |
| job_description | text | None | YES |

## Table: `plans`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| max_rows | integer | None | YES |
| max_vehicles | integer | None | YES |
| max_clients | integer | None | YES |
| max_properties | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| price | numeric | None | YES |
| max_users | integer | None | YES |
| max_storage | integer | None | YES |
| name | character varying | 50 | NO |
| stripe_price_id | character varying | 100 | YES |
| modules | text | None | YES |
| stripe_product_id | character varying | 100 | YES |
| modules_enabled | text | None | YES |

## Table: `certificates`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| created_at | timestamp without time zone | None | YES |
| company_id | integer | None | YES |
| property_id | integer | None | YES |
| data | jsonb | None | YES |
| date_issued | date | None | YES |
| expiry_date | date | None | YES |
| id | integer | None | NO |
| type | character varying | 20 | YES |
| status | character varying | 20 | YES |
| pdf_path | text | None | YES |
| engineer_name | character varying | 100 | YES |

## Table: `properties`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| company_id | integer | None | YES |
| created_at | timestamp without time zone | None | YES |
| gas_expiry | date | None | YES |
| eicr_expiry | date | None | YES |
| pat_expiry | date | None | YES |
| fire_expiry | date | None | YES |
| gas_safety_due | date | None | YES |
| eicr_due | date | None | YES |
| pat_test_due | date | None | YES |
| fire_risk_due | date | None | YES |
| fire_alarm_expiry | date | None | YES |
| id | integer | None | NO |
| epc_expiry | date | None | YES |
| client_id | integer | None | YES |
| status | character varying | 20 | YES |
| address_line1 | text | None | NO |
| tenant_name | text | None | YES |
| tenant_phone | text | None | YES |
| access_info | text | None | YES |
| postcode | text | None | YES |
| type | character varying | 50 | YES |
| key_code | character varying | 100 | YES |
| address_line2 | character varying | 255 | YES |
| city | character varying | 100 | YES |
| county | character varying | 100 | YES |
| tenant | character varying | 100 | YES |

## Table: `suppliers`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| company_id | integer | None | YES |
| name | character varying | 100 | YES |
| email | text | None | YES |

## Table: `overhead_items`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| amount | numeric | None | YES |
| category_id | integer | None | NO |
| id | integer | None | NO |
| date_incurred | date | None | YES |
| frequency | character varying | 20 | YES |
| name | character varying | 100 | NO |
| receipt_path | text | None | YES |

## Table: `job_evidence`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| uploaded_at | timestamp without time zone | None | YES |
| job_id | integer | None | YES |
| uploaded_by | integer | None | YES |
| document_date | date | None | YES |
| id | integer | None | NO |
| filepath | text | None | YES |
| file_type | text | None | YES |

## Table: `maintenance_logs`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| created_at | timestamp without time zone | None | YES |
| date | date | None | YES |
| litres | numeric | None | YES |
| id | integer | None | NO |
| company_id | integer | None | NO |
| vehicle_id | integer | None | NO |
| cost | numeric | None | YES |
| fuel_type | character varying | 50 | YES |
| type | character varying | 50 | YES |
| description | text | None | YES |
| receipt_path | text | None | YES |

## Table: `vehicles`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| service_expiry | date | None | YES |
| repair_cost | numeric | None | YES |
| assigned_driver_id | integer | None | YES |
| mileage | integer | None | YES |
| telematics_data | jsonb | None | YES |
| last_updated_time | timestamp without time zone | None | YES |
| mot_expiry | date | None | YES |
| tax_expiry | date | None | YES |
| ins_expiry | date | None | YES |
| id | integer | None | NO |
| daily_cost | real | None | YES |
| company_id | integer | None | YES |
| reg_plate | text | None | YES |
| make_model | text | None | YES |
| tracking_device_id | text | None | YES |
| status | text | None | YES |
| tracker_url | text | None | YES |
| notes | text | None | YES |
| defect_image_url | text | None | YES |
| defect_notes | text | None | YES |
| telematics_provider | character varying | 50 | YES |

## Table: `transactions`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| amount | real | None | YES |
| created_at | timestamp without time zone | None | YES |
| company_id | integer | None | YES |
| description | text | None | YES |
| reference | text | None | YES |
| date | text | None | YES |
| type | text | None | YES |
| category | text | None | YES |

## Table: `users`

| Column Name | Data Type | Max Length | Nullable |
|---|---|---|---|
| id | integer | None | NO |
| scale_preference | real | None | YES |
| created_at | timestamp without time zone | None | YES |
| company_id | integer | None | YES |
| theme_preference | text | None | YES |
| name | text | None | YES |
| email | text | None | YES |
| username | text | None | YES |
| password_hash | character varying | 255 | YES |
| role | text | None | YES |

