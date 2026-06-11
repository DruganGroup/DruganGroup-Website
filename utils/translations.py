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
    },
    
    # Public Marketing Site
    'Pricing': {
        'es': 'Precios', 'fr': 'Tarifs', 'de': 'Preise',
        'ar': 'التسعير', 'zh': '定价', 'hi': 'मूल्य निर्धारण', 'pt': 'Preços'
    },
    'Features': {
        'es': 'Características', 'fr': 'Fonctionnalités', 'de': 'Funktionen',
        'ar': 'الميزات', 'zh': '功能', 'hi': 'विशेषताएं', 'pt': 'Recursos'
    },
    'Login': {
        'es': 'Iniciar Sesión', 'fr': 'Connexion', 'de': 'Anmelden',
        'ar': 'تسجيل الدخول', 'zh': '登录', 'hi': 'लॉग इन', 'pt': 'Entrar'
    },
    'Sign Up': {
        'es': 'Regístrate', 'fr': "S'inscrire", 'de': 'Registrieren',
        'ar': 'التسجيل', 'zh': '注册', 'hi': 'साइन अप करें', 'pt': 'Inscrever-se'
    },
    'Global Reach': {
        'es': 'Alcance Global', 'fr': 'Portée Mondiale', 'de': 'Globale Reichweite',
        'ar': 'الوصول العالمي', 'zh': '全球范围', 'hi': 'वैश्विक पहुंच', 'pt': 'Alcance Global'
    },
    'Global Compliance': {
        'es': 'Cumplimiento Global', 'fr': 'Conformité Mondiale', 'de': 'Globale Compliance',
        'ar': 'الامتثال العالمي', 'zh': '全球合规', 'hi': 'वैश्विक अनुपालन', 'pt': 'Conformidade Global'
    }
,
    'Reference': {
        'es': 'Referencia', 'fr': 'Référence', 'de': 'Referenz',
        'ar': 'مرجع', 'zh': '参考', 'hi': 'संदर्भ', 'pt': 'Referência'
    },
    'Client': {
        'es': 'Cliente', 'fr': 'Client', 'de': 'Kunde',
        'ar': 'عميل', 'zh': '客户', 'hi': 'ग्राहक', 'pt': 'Cliente'
    },
    'Action': {
        'es': 'Acción', 'fr': 'Action', 'de': 'Aktion',
        'ar': 'إجراء', 'zh': '操作', 'hi': 'कार्रवाई', 'pt': 'Ação'
    },
    'Actions': {
        'es': 'Acciones', 'fr': 'Actions', 'de': 'Aktionen',
        'ar': 'إجراءات', 'zh': '操作', 'hi': 'कार्रवाई', 'pt': 'Ações'
    },
    'Add': {
        'es': 'Añadir', 'fr': 'Ajouter', 'de': 'Hinzufügen',
        'ar': 'إضافة', 'zh': '添加', 'hi': 'जोड़ें', 'pt': 'Adicionar'
    },
    'Delete': {
        'es': 'Eliminar', 'fr': 'Supprimer', 'de': 'Löschen',
        'ar': 'حذف', 'zh': '删除', 'hi': 'हटाएं', 'pt': 'Excluir'
    },
    'Edit': {
        'es': 'Editar', 'fr': 'Modifier', 'de': 'Bearbeiten',
        'ar': 'تعديل', 'zh': '编辑', 'hi': 'संपादित करें', 'pt': 'Editar'
    },
    'View': {
        'es': 'Ver', 'fr': 'Voir', 'de': 'Ansehen',
        'ar': 'عرض', 'zh': '查看', 'hi': 'देखें', 'pt': 'Ver'
    },
    'Cancel': {
        'es': 'Cancelar', 'fr': 'Annuler', 'de': 'Abbrechen',
        'ar': 'إلغاء', 'zh': '取消', 'hi': 'रद्द करें', 'pt': 'Cancelar'
    },
    'Search': {
        'es': 'Buscar', 'fr': 'Chercher', 'de': 'Suche',
        'ar': 'بحث', 'zh': '搜索', 'hi': 'खोज', 'pt': 'Buscar'
    },
    'Notes': {
        'es': 'Notas', 'fr': 'Notes', 'de': 'Notizen',
        'ar': 'ملاحظات', 'zh': '注释', 'hi': 'टिप्पणियाँ', 'pt': 'Notas'
    },
    'Address': {
        'es': 'Dirección', 'fr': 'Adresse', 'de': 'Adresse',
        'ar': 'عنوان', 'zh': '地址', 'hi': 'पता', 'pt': 'Endereço'
    },
    'Email': {
        'es': 'Correo', 'fr': 'Email', 'de': 'E-Mail',
        'ar': 'بريد إلكتروني', 'zh': '电子邮件', 'hi': 'ईमेल', 'pt': 'Email'
    },
    'Phone': {
        'es': 'Teléfono', 'fr': 'Téléphone', 'de': 'Telefon',
        'ar': 'هاتف', 'zh': '电话', 'hi': 'फ़ोन', 'pt': 'Telefone'
    },
    'Name': {
        'es': 'Nombre', 'fr': 'Nom', 'de': 'Name',
        'ar': 'اسم', 'zh': '姓名', 'hi': 'नाम', 'pt': 'Nome'
    },
    'Type': {
        'es': 'Tipo', 'fr': 'Type', 'de': 'Typ',
        'ar': 'نوع', 'zh': '类型', 'hi': 'प्रकार', 'pt': 'Tipo'
    },
    'Category': {
        'es': 'Categoría', 'fr': 'Catégorie', 'de': 'Kategorie',
        'ar': 'فئة', 'zh': '类别', 'hi': 'श्रेणी', 'pt': 'Categoria'
    },
    'Cost': {
        'es': 'Costo', 'fr': 'Coût', 'de': 'Kosten',
        'ar': 'تكلفة', 'zh': '成本', 'hi': 'लागत', 'pt': 'Custo'
    },
    'Price': {
        'es': 'Precio', 'fr': 'Prix', 'de': 'Preis',
        'ar': 'سعر', 'zh': '价格', 'hi': 'कीमत', 'pt': 'Preço'
    },
    'Quantity': {
        'es': 'Cantidad', 'fr': 'Quantité', 'de': 'Menge',
        'ar': 'كمية', 'zh': '数量', 'hi': 'मात्रा', 'pt': 'Quantidade'
    },
    'Hours': {
        'es': 'Horas', 'fr': 'Heures', 'de': 'Stunden',
        'ar': 'ساعات', 'zh': '小时', 'hi': 'घंटे', 'pt': 'Horas'
    },
    'Rate': {
        'es': 'Tarifa', 'fr': 'Taux', 'de': 'Satz',
        'ar': 'معدل', 'zh': '费率', 'hi': 'दर', 'pt': 'Taxa'
    },
    'Staff': {
        'es': 'Personal', 'fr': 'Personnel', 'de': 'Personal',
        'ar': 'طاقم العمل', 'zh': '员工', 'hi': 'कर्मचारी', 'pt': 'Equipe'
    },
    'Materials': {
        'es': 'Materiales', 'fr': 'Matériaux', 'de': 'Materialien',
        'ar': 'مواد', 'zh': '材料', 'hi': 'सामग्री', 'pt': 'Materiais'
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
