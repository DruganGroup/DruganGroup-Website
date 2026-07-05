from db import get_db
from datetime import date, timedelta
from utils.date_utils import format_date

def get_finance_dashboard_data(comp_id):
    """Aggregates all SQL logic required for the Finance Dashboard."""
    conn = get_db()
    if not conn:
        return {}
        
    cur = conn.cursor()
    
    # 1. Currency
    cur.execute("SELECT value FROM settings WHERE key='currency_symbol' AND company_id=%s", (comp_id,))
    res = cur.fetchone()
    currency = res[0] if res else '£'

    # 2. Total Income
    cur.execute("""
        SELECT COALESCE(SUM(total), 0) 
        FROM invoices 
        WHERE company_id = %s AND status != 'Void'
    """, (comp_id,))
    total_income = float(cur.fetchone()[0])

    # 3. Fleet Cost
    cur.execute("SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs WHERE company_id = %s", (comp_id,))
    fleet_cost = float(cur.fetchone()[0])
    
    # 4. Overhead
    cur.execute("""
        SELECT COALESCE(SUM(amount), 0) 
        FROM overhead_items 
        JOIN overhead_categories c ON overhead_items.category_id = c.id 
        WHERE c.company_id = %s
    """, (comp_id,))
    monthly_overhead = float(cur.fetchone()[0])
    
    total_expense = fleet_cost + monthly_overhead
    total_balance = total_income - total_expense
    break_even = (monthly_overhead * 12) / 365 if monthly_overhead > 0 else 0

    # 5. Transactions Feed
    query = """
        (
            SELECT 
                date_created as date, 
                'Income' as type, 
                'Sales' as category, 
                ref || ' - ' || COALESCE((SELECT name FROM clients WHERE id = invoices.client_id), 'Unknown Client') as description, 
                COALESCE(total, 0) as amount, 
                job_id
            FROM invoices 
            WHERE company_id = %s AND status = 'Paid'
        )
        UNION ALL
        (
            SELECT 
                date, 
                'Expense' as type, 
                'Job Cost' as category, 
                COALESCE(description, 'Uncategorized Expense'), 
                COALESCE(cost, 0) as amount, 
                job_id
            FROM job_expenses 
            WHERE company_id = %s
        )
        UNION ALL
        (
            SELECT 
                date_incurred as date, 
                'Expense' as type, 
                'Overhead' as category, 
                COALESCE(name, 'General Overhead'), 
                COALESCE(amount, 0) as amount,
                NULL as job_id
            FROM overhead_items 
            WHERE category_id IN (SELECT id FROM overhead_categories WHERE company_id = %s)
        )
        ORDER BY date DESC 
        LIMIT 15
    """
    cur.execute(query, (comp_id, comp_id, comp_id))
    transactions = cur.fetchall()

    # 6. Chart Data (Past 6 Months)
    chart_labels = []
    chart_income = []
    chart_expense = []
    
    today = date.today()
    for i in range(5, -1, -1):
        d = today - timedelta(days=i*30)
        chart_labels.append(d.strftime("%B"))
        
        cur.execute("""
            SELECT COALESCE(SUM(total), 0) FROM invoices 
            WHERE company_id=%s AND EXTRACT(MONTH FROM date)=%s AND EXTRACT(YEAR FROM date)=%s
        """, (comp_id, d.month, d.year))
        chart_income.append(float(cur.fetchone()[0]))
        
        cur.execute("""
            SELECT COALESCE(SUM(cost), 0) FROM maintenance_logs 
            WHERE company_id=%s AND EXTRACT(MONTH FROM date)=%s AND EXTRACT(YEAR FROM date)=%s
        """, (comp_id, d.month, d.year))
        chart_expense.append(float(cur.fetchone()[0]) + monthly_overhead)

    # 7. Audit Logs
    cur.execute("""
        SELECT created_at, admin_email, action, details 
        FROM audit_logs 
        WHERE company_id = %s OR company_id IS NULL
        ORDER BY created_at DESC LIMIT 5
    """, (comp_id,))
    logs = [{'time': format_date(r[0], "%d/%m %H:%M"), 'user': r[1], 'action': r[2], 'details': r[3]} for r in cur.fetchall()]

    return {
        'currency_symbol': currency,
        'total_income': total_income,
        'total_expense': total_expense,
        'total_balance': total_balance,
        'break_even': break_even,
        'transactions': transactions,
        'chart_labels': chart_labels,
        'chart_income': chart_income,
        'chart_expense': chart_expense,
        'logs': logs
    }

def get_office_dashboard_data(comp_id, user_date_fmt):
    """Aggregates all SQL logic required for the Office Dashboard."""
    conn = get_db()
    if not conn:
        return {}
    cur = conn.cursor()
    
    def process_date(date_val, fmt):
        if not date_val: return "TBC", None, None
        dt = date_val
        if isinstance(date_val, str):
            try: dt = datetime.strptime(date_val[:10], '%Y-%m-%d')
            except: return str(date_val), None, None
        return dt.strftime(fmt), dt.strftime('%d'), dt.strftime('%b')

    # Counters
    cur.execute("SELECT COUNT(*) FROM service_requests WHERE company_id=%s AND status='Pending'", (comp_id,))
    leads_count = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM quotes WHERE company_id=%s AND status IN ('Draft', 'Sent', 'Pending', 'Accepted')", (comp_id,))
    pending_quotes = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM jobs WHERE company_id=%s AND status='Scheduled'", (comp_id,))
    active_jobs = cur.fetchone()[0]
    
    cur.execute("SELECT COUNT(*) FROM invoices WHERE company_id=%s AND status='Unpaid'", (comp_id,))
    unpaid_inv = cur.fetchone()[0]

    # Incoming Requests
    cur.execute("""
        SELECT r.id, c.name, c.phone, r.created_at, r.issue_description, r.client_id
        FROM service_requests r
        JOIN clients c ON r.client_id = c.id
        WHERE r.company_id = %s AND r.status = 'Pending'
        ORDER BY r.created_at DESC LIMIT 5
    """, (comp_id,))
    incoming_requests = [{
        'id': r[0], 'client_name': r[1], 'phone': r[2], 
        'date_added': process_date(r[3], user_date_fmt)[0],
        'desc': r[4], 'client_id': r[5]
    } for r in cur.fetchall()]

    # Recent Quotes
    cur.execute("""
        SELECT q.id, q.reference, c.name, q.total, q.status, q.date
        FROM quotes q
        JOIN clients c ON q.client_id = c.id
        WHERE q.company_id = %s AND q.status IN ('Draft', 'Sent', 'Pending', 'Accepted')
        ORDER BY q.date DESC LIMIT 5
    """, (comp_id,))
    recent_quotes = [{
        'id': r[0], 'ref': r[1], 'client_name': r[2], 
        'total': r[3], 'status': r[4], 'date': format_date(r[5], user_date_fmt)
    } for r in cur.fetchall()]

    # Upcoming Jobs
    cur.execute("""
        SELECT j.id, j.ref, j.site_address, c.name, j.start_date, j.status 
        FROM jobs j 
        LEFT JOIN clients c ON j.client_id = c.id 
        WHERE j.company_id = %s AND j.status = 'Scheduled' 
        ORDER BY j.start_date ASC LIMIT 5
    """, (comp_id,))
    upcoming_jobs = []
    for r in cur.fetchall():
        fmt_full, day_num, month_abbr = process_date(r[4], user_date_fmt)
        upcoming_jobs.append({
            'id': r[0], 'ref': r[1], 'address': r[2], 'client_name': r[3],
            'start_date_fmt': fmt_full, 'day': day_num, 'month': month_abbr
        })

    # Uninvoiced Jobs
    cur.execute("""
        SELECT j.id, j.ref, c.name, j.quote_total
        FROM jobs j
        LEFT JOIN invoices i ON j.id = i.job_id
        LEFT JOIN clients c ON j.client_id = c.id
        WHERE j.company_id = %s AND j.status = 'Completed' AND i.id IS NULL
        ORDER BY j.start_date DESC LIMIT 5
    """, (comp_id,))
    uninvoiced_jobs = [{'id': r[0], 'ref': r[1], 'client_name': r[2], 'total': r[3]} for r in cur.fetchall()]

    # Pipeline
    cur.execute("SELECT status, COUNT(*), SUM(total) FROM quotes WHERE company_id=%s GROUP BY status", (comp_id,))
    pipeline = { 'Draft': {'count': 0, 'value': 0}, 'Sent': {'count': 0, 'value': 0}, 'Accepted': {'count': 0, 'value': 0}, 'Rejected': {'count': 0, 'value': 0} }
    for r in cur.fetchall():
        if r[0] in pipeline:
            pipeline[r[0]]['count'] = r[1]
            pipeline[r[0]]['value'] = float(r[2] or 0)

    # Dropdowns
    cur.execute("SELECT id, name FROM clients WHERE company_id=%s ORDER BY name", (comp_id,))
    clients = [{'id': r[0], 'name': r[1]} for r in cur.fetchall()]
    
    cur.execute("SELECT id, reg_plate FROM vehicles WHERE company_id=%s AND status='Active'", (comp_id,))
    vehicles = [{'id': r[0], 'reg': r[1]} for r in cur.fetchall()]

    return {
        'leads_count': leads_count,
        'pending_quotes': pending_quotes,
        'active_jobs': active_jobs,
        'unpaid_inv': unpaid_inv,
        'incoming_requests': incoming_requests,
        'recent_quotes': recent_quotes,
        'upcoming_jobs': upcoming_jobs,
        'uninvoiced_jobs': uninvoiced_jobs,
        'pipeline': pipeline,
        'clients': clients,
        'vehicles': vehicles
    }
