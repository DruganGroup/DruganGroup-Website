# utils/translations.py

# A lightweight dictionary-based translation engine
# Keys are English strings, values are dictionaries of language translations.

LANGUAGES = {
    'en': 'English',
    'es': 'Español (Spanish)',
    'fr': 'Français (French)',
    'de': 'Deutsch (German)',
    'ar': 'العربية (Arabic)',
    'zh': '中文 (Mandarin)',
    'hi': 'हिन्दी (Hindi)',
    'pt': 'Português (Portuguese)'
}

# Determines if a language requires Right-to-Left (RTL) layout
RTL_LANGUAGES = ['ar']

TRANSLATIONS = {
    # General Sidebar & Navigation
    'Dashboard': {
        'es': 'Panel', 'fr': 'Tableau de bord', 'de': 'Dashboard',
        'ar': 'لوحة القيادة', 'zh': '仪表板', 'hi': 'डैशबोर्ड', 'pt': 'Painel'
    },
    'Clients': {
        'es': 'Clientes', 'fr': 'Clients', 'de': 'Kunden',
        'ar': 'العملاء', 'zh': '客户', 'hi': 'ग्राहक', 'pt': 'Clientes'
    },
    'Jobs': {
        'es': 'Trabajos', 'fr': 'Emplois', 'de': 'Aufträge',
        'ar': 'الوظائف', 'zh': '工作', 'hi': 'नौकरियां', 'pt': 'Trabalhos'
    },
    'Quotes': {
        'es': 'Cotizaciones', 'fr': 'Devis', 'de': 'Angebote',
        'ar': 'عروض الأسعار', 'zh': '报价', 'hi': 'उद्धरण', 'pt': 'Cotações'
    },
    'Invoices': {
        'es': 'Facturas', 'fr': 'Factures', 'de': 'Rechnungen',
        'ar': 'الفواتير', 'zh': '发票', 'hi': 'चालान', 'pt': 'Faturas'
    },
    'Settings': {
        'es': 'Ajustes', 'fr': 'Paramètres', 'de': 'Einstellungen',
        'ar': 'الإعدادات', 'zh': '设置', 'hi': 'सेटिंग्स', 'pt': 'Configurações'
    },
    'Save': {
        'es': 'Guardar', 'fr': 'Enregistrer', 'de': 'Speichern',
        'ar': 'حفظ', 'zh': '保存', 'hi': 'सहेजें', 'pt': 'Salvar'
    },
    
    # Settings Page
    'General Settings': {
        'es': 'Ajustes Generales', 'fr': 'Paramètres Généraux', 'de': 'Allgemeine Einstellungen',
        'ar': 'الإعدادات العامة', 'zh': '常规设置', 'hi': 'सामान्य सेटिंग्स', 'pt': 'Configurações Gerais'
    },
    'System Language': {
        'es': 'Idioma del Sistema', 'fr': 'Langue du Système', 'de': 'Systemsprache',
        'ar': 'لغة النظام', 'zh': '系统语言', 'hi': 'सिस्टम भाषा', 'pt': 'Idioma do Sistema'
    },
    'Company Name': {
        'es': 'Nombre de la Empresa', 'fr': 'Nom de la Société', 'de': 'Firmenname',
        'ar': 'اسم الشركة', 'zh': '公司名称', 'hi': 'कंपनी का नाम', 'pt': 'Nome da Empresa'
    },
    
    # Financial Terms
    'Revenue': {
        'es': 'Ingresos', 'fr': 'Revenus', 'de': 'Einnahmen',
        'ar': 'إيرادات', 'zh': '收入', 'hi': 'राजस्व', 'pt': 'Receita'
    },
    'Expenses': {
        'es': 'Gastos', 'fr': 'Dépenses', 'de': 'Ausgaben',
        'ar': 'نفقات', 'zh': '支出', 'hi': 'खर्च', 'pt': 'Despesas'
    },
    'Profit': {
        'es': 'Ganancias', 'fr': 'Bénéfice', 'de': 'Gewinn',
        'ar': 'الربح', 'zh': '利润', 'hi': 'लाभ', 'pt': 'Lucro'
    },
    'Status': {
        'es': 'Estado', 'fr': 'Statut', 'de': 'Status',
        'ar': 'الحالة', 'zh': '状态', 'hi': 'स्थिति', 'pt': 'Status'
    },
    'Due Date': {
        'es': 'Fecha de Vencimiento', 'fr': "Date d'échéance", 'de': 'Fälligkeitsdatum',
        'ar': 'تاريخ الاستحقاق', 'zh': '到期日', 'hi': 'नियत तारीख', 'pt': 'Data de Vencimento'
    },
    'Total': {
        'es': 'Total', 'fr': 'Total', 'de': 'Gesamt',
        'ar': 'المجموع', 'zh': '总计', 'hi': 'कुल', 'pt': 'Total'
    },
    'Total Income': {
        'es': 'Ingresos Totales', 'fr': 'Revenu Total', 'de': 'Gesamteinkommen',
        'ar': 'إجمالي الدخل', 'zh': '总收入', 'hi': 'कुल आय', 'pt': 'Renda Total'
    },
    'Total Expenses': {
        'es': 'Gastos Totales', 'fr': 'Dépenses Totales', 'de': 'Gesamtausgaben',
        'ar': 'إجمالي النفقات', 'zh': '总支出', 'hi': 'कुल व्यय', 'pt': 'Despesas Totais'
    },
    'Net Profit': {
        'es': 'Beneficio Neto', 'fr': 'Bénéfice Net', 'de': 'Reingewinn',
        'ar': 'صافي الربح', 'zh': '净利润', 'hi': 'शुद्ध लाभ', 'pt': 'Lucro Líquido'
    },
    'Date': {
        'es': 'Fecha', 'fr': 'Date', 'de': 'Datum',
        'ar': 'تاريخ', 'zh': '日期', 'hi': 'तारीख', 'pt': 'Data'
    },
    'Description': {
        'es': 'Descripción', 'fr': 'Description', 'de': 'Beschreibung',
        'ar': 'وصف', 'zh': '描述', 'hi': 'विवरण', 'pt': 'Descrição'
    },
    'Value': {
        'es': 'Valor', 'fr': 'Valeur', 'de': 'Wert',
        'ar': 'القيمة', 'zh': '价值', 'hi': 'मूल्य', 'pt': 'Valor'
    },
    'Start Date': {
        'es': 'Fecha de Inicio', 'fr': 'Date de Début', 'de': 'Startdatum',
        'ar': 'تاريخ البدء', 'zh': '开始日期', 'hi': 'आरंभ करने की तिथि', 'pt': 'Data de Início'
    },
    'Amount': {
        'es': 'Monto', 'fr': 'Montant', 'de': 'Betrag',
        'ar': 'كمية', 'zh': '金额', 'hi': 'रकम', 'pt': 'Montante'
    },
    'New Requests': {
        'es': 'Nuevas Solicitudes', 'fr': 'Nouvelles Demandes', 'de': 'Neue Anfragen',
        'ar': 'طلبات جديدة', 'zh': '新请求', 'hi': 'नए अनुरोध', 'pt': 'Novos Pedidos'
    },
    'Pending Quotes': {
        'es': 'Cotizaciones Pendientes', 'fr': 'Devis en Attente', 'de': 'Ausstehende Angebote',
        'ar': 'عروض أسعار معلقة', 'zh': '待定报价', 'hi': 'लंबित उद्धरण', 'pt': 'Cotações Pendentes'
    },
    'Active Jobs': {
        'es': 'Trabajos Activos', 'fr': 'Emplois Actifs', 'de': 'Aktive Jobs',
        'ar': 'وظائف نشطة', 'zh': '活跃工作', 'hi': 'सक्रिय नौकरियां', 'pt': 'Trabalhos Ativos'
    },
    'Unpaid Invoices': {
        'es': 'Facturas Impagas', 'fr': 'Factures Impayées', 'de': 'Unbezahlte Rechnungen',
        'ar': 'فواتير غير مدفوعة', 'zh': '未发票', 'hi': 'अवैतनिक चालान', 'pt': 'Faturas Não Pagas'
    }
}

def get_translation(text, lang_code='en'):
    """
    Returns the translated string for a given language code.
    If the translation doesn't exist, falls back to the original English text.
    """
    if lang_code == 'en' or not lang_code:
        return text
        
    translation_dict = TRANSLATIONS.get(text)
    if not translation_dict:
        return text
        
    return translation_dict.get(lang_code, text)

def get_lang_direction(lang_code):
    """Returns 'rtl' for Arabic, otherwise 'ltr'"""
    return 'rtl' if lang_code in RTL_LANGUAGES else 'ltr'
