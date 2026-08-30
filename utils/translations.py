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
    },
    'Overview': {
        'es': 'Resumen', 'fr': 'Aperçu', 'de': 'Übersicht',
        'ar': 'نظرة عامة', 'zh': '概述', 'hi': 'अवलोकन', 'pt': 'Visão Geral'
    },
    'Sales Ledger': {
        'es': 'Libro de Ventas', 'fr': 'Grand Livre des Ventes', 'de': 'Verkaufsbuch',
        'ar': 'دفتر المبيعات', 'zh': '销售分类帐', 'hi': 'बिक्री बही', 'pt': 'Livro de Vendas'
    },
    'Sorting Office': {
        'es': 'Oficina de Clasificación', 'fr': 'Bureau de Tri', 'de': 'Sortierbüro',
        'ar': 'مكتب الفرز', 'zh': '分拣室', 'hi': 'सॉर्टिंग कार्यालय', 'pt': 'Classificação de Recibos'
    },
    'Profit Analysis': {
        'es': 'Análisis de Beneficios', 'fr': 'Analyse des Bénéfices', 'de': 'Gewinnanalyse',
        'ar': 'تحليل الأرباح', 'zh': '利润分析', 'hi': 'लाभ विश्लेषण', 'pt': 'Análise de Lucro'
    },
    'Fleet Costs': {
        'es': 'Costos de Flota', 'fr': 'Coûts de la Flotte', 'de': 'Flottenkosten',
        'ar': 'تكاليف الأسطول', 'zh': '车队成本', 'hi': 'फ्लीट लागत', 'pt': 'Custos da Frota'
    },
    'Material Library': {
        'es': 'Biblioteca de Materiales', 'fr': 'Bibliothèque de Matériaux', 'de': 'Materialbibliothek',
        'ar': 'مكتبة المواد', 'zh': '材料库', 'hi': 'सामग्री लाइब्रेरी', 'pt': 'Biblioteca de Materiais'
    },
    'Staff Manager': {
        'es': 'Gestor de Personal', 'fr': 'Gestionnaire du Personnel', 'de': 'Personalmanager',
        'ar': 'مدير الموظفين', 'zh': '员工管理', 'hi': 'कर्मचारी प्रबंधक', 'pt': 'Gestor de Pessoal'
    },
    'Timesheets': {
        'es': 'Hojas de Horas', 'fr': 'Feuilles de Temps', 'de': 'Stundenzettel',
        'ar': 'سجلات الدوام', 'zh': '工时单', 'hi': 'समय पत्रक', 'pt': 'Folhas de Ponto'
    },
    'Holiday & Leave': {
        'es': 'Vacaciones y Permisos', 'fr': 'Congés et Absences', 'de': 'Urlaub & Abwesenheit',
        'ar': 'الإجازات والعطلات', 'zh': '假期与休假', 'hi': 'छुट्टी और अवकाश', 'pt': 'Férias e Licenças'
    },
    'Run Payroll': {
        'es': 'Ejecutar Nómina', 'fr': 'Lancer la Paie', 'de': 'Gehaltsabrechnung',
        'ar': 'تشغيل الرواتب', 'zh': '运行工资单', 'hi': 'पेरोल चलाएं', 'pt': 'Processar Folha'
    },
    'Daily Break-Even': {
        'es': 'Punto de Equilibrio Diario', 'fr': 'Seuil de Rentabilité Quotidien', 'de': 'Täglicher Break-Even',
        'ar': 'نقطة التعادل اليومية', 'zh': '每日收支平衡', 'hi': 'दैनिक ब्रेक-ईवन', 'pt': 'Ponto de Equilíbrio Diário'
    },
    'Daily Target': {
        'es': 'Objetivo Diario', 'fr': 'Objectif Quotidien', 'de': 'Tagesziel',
        'ar': 'الهدف اليومي', 'zh': '每日目标', 'hi': 'दैनिक लक्ष्य', 'pt': 'Meta Diária'
    },
    'Paid Income': {
        'es': 'Ingresos Cobrados', 'fr': 'Revenus Encaissés', 'de': 'Bezahlte Einnahmen',
        'ar': 'الدخل المدفوع', 'zh': '已付收入', 'hi': 'भुगतान की गई आय', 'pt': 'Renda Recebida'
    },
    'Staff Wages': {
        'es': 'Salarios del Personal', 'fr': 'Salaires du Personnel', 'de': 'Personallöhne',
        'ar': 'أجور الموظفين', 'zh': '员工工资', 'hi': 'कर्मचारी वेतन', 'pt': 'Salários da Equipe'
    },
    'Financial Overview': {
        'es': 'Resumen Financiero', 'fr': 'Aperçu Financier', 'de': 'Finanzübersicht',
        'ar': 'نظرة عامة مالية', 'zh': '财务概览', 'hi': 'वित्तीय अवलोकन', 'pt': 'Visão Financeira'
    },
    'Cash Flow Trends': {
        'es': 'Tendencias de Flujo de Caja', 'fr': 'Flux de Trésorerie', 'de': 'Cashflow-Trends',
        'ar': 'اتجاهات التدفق النقدي', 'zh': '现金流趋势', 'hi': 'कैश फ्लो रुझान', 'pt': 'Fluxo de Caixa'
    },
    'Recent Transactions': {
        'es': 'Transacciones Recientes', 'fr': 'Transactions Récentes', 'de': 'Letzte Transaktionen',
        'ar': 'المعاملات الأخيرة', 'zh': '最近交易', 'hi': 'हाल के लेनदेन', 'pt': 'Transações Recentes'
    },
    'System Audit Log': {
        'es': 'Registro de Auditoría', 'fr': "Journal d'Audit", 'de': 'System-Audit-Protokoll',
        'ar': 'سجل تدقيق النظام', 'zh': '系统审计日志', 'hi': 'ऑडिट लॉग', 'pt': 'Registro de Auditoria'
    },
    'Audit Logs': {
        'es': 'Registros de Auditoría', 'fr': "Journaux d'Audit", 'de': 'Audit-Protokolle',
        'ar': 'سجلات التدقيق', 'zh': '审计日志', 'hi': 'ऑडिट लॉग', 'pt': 'Logs de Auditoria'
    },
    'Export CSV': {
        'es': 'Exportar CSV', 'fr': 'Exporter CSV', 'de': 'CSV exportieren',
        'ar': 'تصدير CSV', 'zh': '导出CSV', 'hi': 'CSV निर्यात करें', 'pt': 'Exportar CSV'
    },
    'Refresh Data': {
        'es': 'Actualizar Datos', 'fr': 'Actualiser', 'de': 'Aktualisieren',
        'ar': 'تحديث البيانات', 'zh': '刷新数据', 'hi': 'डेटा रीफ्रेश करें', 'pt': 'Atualizar Dados'
    },
    'Year': {
        'es': 'Año', 'fr': 'Année', 'de': 'Jahr',
        'ar': 'سنة', 'zh': '年份', 'hi': 'वर्ष', 'pt': 'Ano'
    },
    'Profit Margin': {
        'es': 'Margen de Beneficio', 'fr': 'Marge Bénéficiaire', 'de': 'Gewinnspanne',
        'ar': 'هامش الربح', 'zh': '利润率', 'hi': 'लाभ मार्जिन', 'pt': 'Margem de Lucro'
    },
    'Filter': {
        'es': 'Filtrar', 'fr': 'Filtrer', 'de': 'Filtern',
        'ar': 'تصفية', 'zh': '筛选', 'hi': 'फ़िल्टर', 'pt': 'Filtrar'
    },
    'Mission Control': {
        'es': 'Control de Misión', 'fr': 'Centre de Contrôle', 'de': 'Leitstelle',
        'ar': 'مركز التحكم', 'zh': '控制中心', 'hi': 'नियंत्रण केंद्र', 'pt': 'Controle de Missão'
    },
    'Master Schedule': {
        'es': 'Horario Maestro', 'fr': 'Planning Principal', 'de': 'Hauptzeitplan',
        'ar': 'الجدول الرئيسي', 'zh': '总日程表', 'hi': 'मुख्य अनुसूची', 'pt': 'Cronograma Principal'
    },
    'Service Desk': {
        'es': 'Mesa de Ayuda', 'fr': 'Centre de Service', 'de': 'Service Desk',
        'ar': 'مكتب الخدمة', 'zh': '服务台', 'hi': 'सेवा डेस्क', 'pt': 'Central de Atendimento'
    },
    'Communications': {
        'es': 'Comunicaciones', 'fr': 'Communications', 'de': 'Kommunikation',
        'ar': 'الاتصالات', 'zh': '通讯', 'hi': 'संचार', 'pt': 'Comunicações'
    },
    'Live Operations': {
        'es': 'Operaciones en Vivo', 'fr': 'Opérations en Direct', 'de': 'Live-Betrieb',
        'ar': 'العمليات المباشرة', 'zh': '实时运营', 'hi': 'लाइव संचालन', 'pt': 'Operações ao Vivo'
    },
    'Clients & Portfolios': {
        'es': 'Clientes y Carteras', 'fr': 'Clients et Portefeuilles', 'de': 'Kunden & Portfolios',
        'ar': 'العملاء والمحافظ', 'zh': '客户与投资组合', 'hi': 'ग्राहक और पोर्टफोलियो', 'pt': 'Clientes e Portfólios'
    },
    'Sales & Invoicing': {
        'es': 'Ventas y Facturación', 'fr': 'Ventes et Facturation', 'de': 'Verkauf & Rechnungsstellung',
        'ar': 'المبيعات والفوترة', 'zh': '销售与开票', 'hi': 'बिक्री और चालान', 'pt': 'Vendas e Faturamento'
    },
    'Fleet Manager': {
        'es': 'Gestor de Flota', 'fr': 'Gestionnaire de Flotte', 'de': 'Flottenmanager',
        'ar': 'مدير الأسطول', 'zh': '车队经理', 'hi': 'फ्लीट प्रबंधक', 'pt': 'Gerente de Frota'
    },
    'New Job': {
        'es': 'Nuevo Trabajo', 'fr': 'Nouveau Travail', 'de': 'Neuer Auftrag',
        'ar': 'عمل جديد', 'zh': '新工作', 'hi': 'नया काम', 'pt': 'Novo Trabalho'
    },
    'New Quote': {
        'es': 'Nueva Cotización', 'fr': 'Nouveau Devis', 'de': 'Neues Angebot',
        'ar': 'عرض سعر جديد', 'zh': '新报价', 'hi': 'नया कोट', 'pt': 'Novo Orçamento'
    },
    'New Invoice': {
        'es': 'Nueva Factura', 'fr': 'Nouvelle Facture', 'de': 'Neue Rechnung',
        'ar': 'فاتورة جديدة', 'zh': '新发票', 'hi': 'नया बिल', 'pt': 'Nova Fatura'
    },
    'Add Property': {
        'es': 'Añadir Propiedad', 'fr': 'Ajouter Propriété', 'de': 'Objekt hinzufügen',
        'ar': 'إضافة عقار', 'zh': '添加物业', 'hi': 'संपत्ति जोड़ें', 'pt': 'Adicionar Imóvel'
    },
    'Property': {
        'es': 'Propiedad', 'fr': 'Propriété', 'de': 'Objekt',
        'ar': 'عقار', 'zh': '物业', 'hi': 'संपत्ति', 'pt': 'Imóvel'
    },
    'Properties': {
        'es': 'Propiedades', 'fr': 'Propriétés', 'de': 'Objekte',
        'ar': 'العقارات', 'zh': '物业', 'hi': 'संपत्तियां', 'pt': 'Imóveis'
    },
    'Tenant': {
        'es': 'Inquilino', 'fr': 'Locataire', 'de': 'Mieter',
        'ar': 'المستأجر', 'zh': '租客', 'hi': 'किरायेदार', 'pt': 'Inquilino'
    },
    'Key Safe': {
        'es': 'Caja de Llaves', 'fr': 'Boîte à Clés', 'de': 'Schlüsselsafe',
        'ar': 'خزنة المفاتيح', 'zh': '钥匙盒', 'hi': 'कुंजी सुरक्षित', 'pt': 'Cofre de Chaves'
    },
    'Scheduled': {
        'es': 'Programado', 'fr': 'Programmé', 'de': 'Geplant',
        'ar': 'مجدول', 'zh': '已安排', 'hi': 'निर्धारित', 'pt': 'Agendado'
    },
    'In Progress': {
        'es': 'En Progreso', 'fr': 'En Cours', 'de': 'In Bearbeitung',
        'ar': 'قيد التنفيذ', 'zh': '进行中', 'hi': 'प्रगति में है', 'pt': 'Em Progresso'
    },
    'Completed': {
        'es': 'Completado', 'fr': 'Terminé', 'de': 'Abgeschlossen',
        'ar': 'مكتمل', 'zh': '已完成', 'hi': 'पुरा हुआ', 'pt': 'Concluído'
    },
    'Paid': {
        'es': 'Pagado', 'fr': 'Payé', 'de': 'Bezahlt',
        'ar': 'مدفوع', 'zh': '已付款', 'hi': 'भुगतान किया', 'pt': 'Pago'
    },
    'Unpaid': {
        'es': 'No Pagado', 'fr': 'Non Payé', 'de': 'Unbezahlt',
        'ar': 'غير مدفوع', 'zh': '未付款', 'hi': 'अदत्त', 'pt': 'Não Pago'
    },
    'Overdue': {
        'es': 'Vencido', 'fr': 'En Retard', 'de': 'Überfällig',
        'ar': 'متأخر', 'zh': '逾期', 'hi': 'अतिदेय', 'pt': 'Atrasado'
    },
    'Accepted': {
        'es': 'Aceptado', 'fr': 'Accepté', 'de': 'Akzeptiert',
        'ar': 'مقبول', 'zh': '已接受', 'hi': 'स्वीकृत', 'pt': 'Aceito'
    },
    'Declined': {
        'es': 'Rechazado', 'fr': 'Refusé', 'de': 'Abgelehnt',
        'ar': 'مرفوض', 'zh': '已拒绝', 'hi': 'अस्वीकृत', 'pt': 'Recusado'
    },
    'Draft': {
        'es': 'Borrador', 'fr': 'Brouillon', 'de': 'Entwurf',
        'ar': 'مسودة', 'zh': '草稿', 'hi': 'प्रारूप', 'pt': 'Rascunho'
    },
    'Sent': {
        'es': 'Enviado', 'fr': 'Envoyé', 'de': 'Gesendet',
        'ar': 'تم الإرسال', 'zh': '已发送', 'hi': 'भेजा गया', 'pt': 'Enviado'
    },
    'Compliance Alerts': {
        'es': 'Alertas de Cumplimiento', 'fr': 'Alertes de Conformité', 'de': 'Compliance-Warnungen',
        'ar': 'تنبيهات الامتثال', 'zh': '合规警告', 'hi': 'अनुपालन अलर्ट', 'pt': 'Alertas de Conformidade'
    },
    'Review & Approve': {
        'es': 'Revisar y Aprobar', 'fr': 'Examiner et Approuver', 'de': 'Prüfen & Genehmigen',
        'ar': 'مراجعة وموافقة', 'zh': '审查并批准', 'hi': 'समीक्षा करें और स्वीकृत करें', 'pt': 'Revisar e Aprovar'
    },
    'Pay Online': {
        'es': 'Pagar en Línea', 'fr': 'Payer en Ligne', 'de': 'Online bezahlen',
        'ar': 'الدفع عبر الإنترنت', 'zh': '在线付款', 'hi': 'ऑनलाइन भुगतान करें', 'pt': 'Pagar Online'
    },
    'Download PDF': {
        'es': 'Descargar PDF', 'fr': 'Télécharger PDF', 'de': 'PDF herunterladen',
        'ar': 'تحميل PDF', 'zh': '下载PDF', 'hi': 'पीडीएफ डाउनलोड करें', 'pt': 'Baixar PDF'
    },
    'Email Client': {
        'es': 'Enviar Correo al Cliente', 'fr': 'Envoyer un Email au Client', 'de': 'Kunden per E-Mail anschreiben',
        'ar': 'إرسال بريد للعميل', 'zh': '给客户发邮件', 'hi': 'ग्राहक को ईमेल करें', 'pt': 'Enviar Email ao Cliente'
    },
    'Sign Out': {
        'es': 'Cerrar Sesión', 'fr': 'Déconnexion', 'de': 'Abmelden',
        'ar': 'تسجيل الخروج', 'zh': '退出', 'hi': 'साइन आउट', 'pt': 'Sair'
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
