# --- services/tax_engine.py ---

class TaxEngine:
    """
    Professional Estimate Engine for Multi-Country Payroll.
    Calculates Tax, Social Security/NI, and Net Pay estimates.
    """
    
    @staticmethod
    def calculate(gross_weekly, country_code='UK'):
        gross_annual = gross_weekly * 52
        tax = 0.0
        social = 0.0 
        
        country = (country_code or 'UK').upper()
        if country_code == 'UK':
            # National Insurance (Approx 8% above threshold)
            if gross_annual > 12570:
                social = (gross_annual - 12570) * 0.08
            
            # Income Tax (Standard Personal Allowance ~£12,570)
            taxable = max(0, gross_annual - 12570)
            if taxable > 37700: # 40% Higher Rate
                tax = (37700 * 0.20) + ((taxable - 37700) * 0.40)
            else: # 20% Basic Rate
                tax = taxable * 0.20

        # --- 2. UNITED STATES (US) ---
        elif country_code == 'US':
            # FICA (Social Security 6.2% + Medicare 1.45%) = 7.65% flat
            social = gross_annual * 0.0765
            
            # Federal Tax (Simplified 2024 Estimates)
            # Standard Deduction approx $14,600
            taxable = max(0, gross_annual - 14600)
            if taxable > 0:
                if taxable < 11600: tax = taxable * 0.10
                elif taxable < 47150: tax = 1160 + (taxable - 11600) * 0.12
                elif taxable < 100525: tax = 5426 + (taxable - 47150) * 0.22
                else: tax = 17168 + (taxable - 100525) * 0.24

        # --- 3. IRELAND (IE) ---
        elif country == 'IE':
            # USC (Universal Social Charge) - Blended est 3%
            if gross_annual > 13000: social += (gross_annual * 0.03)
            # PRSI (Pay Related Social Insurance) - Approx 4%
            social += (gross_annual * 0.04)
            
            # Income Tax (20% Standard Band up to €42k, 40% higher)
            taxable = gross_annual 
            if taxable > 42000:
                tax = (42000 * 0.20) + ((taxable - 42000) * 0.40)
            else:
                tax = taxable * 0.20

        # --- 4. CANADA (CAN) ---
        elif country in ['CAN', 'CA']:
            # CPP + EI contributions (~7.6% combined capped)
            social = min(gross_annual, 68500) * 0.076
            
            # Federal + Provincial blended income tax
            taxable = max(0, gross_annual - 15705)
            if taxable > 55867:
                tax = (55867 * 0.15) + ((taxable - 55867) * 0.205)
            else:
                tax = taxable * 0.15

        # --- 5. AUSTRALIA (AUS) ---
        elif country in ['AUS', 'AU']:
            # Medicare Levy (2%)
            social = gross_annual * 0.02
            
            # Resident Tax Rates
            if gross_annual > 18200:
                if gross_annual < 45000: tax = (gross_annual - 18200) * 0.19
                elif gross_annual < 120000: tax = 5092 + (gross_annual - 45000) * 0.325
                else: tax = 29467 + (gross_annual - 120000) * 0.37

        # --- 6. NEW ZEALAND (NZ) ---
        elif country == 'NZ':
            # ACC Earners' Levy (~1.6%)
            social = gross_annual * 0.016
            
            # PAYE Tax brackets
            if gross_annual <= 15600:
                tax = gross_annual * 0.105
            elif gross_annual <= 53500:
                tax = (15600 * 0.105) + (gross_annual - 15600) * 0.175
            elif gross_annual <= 78100:
                tax = (15600 * 0.105) + (37900 * 0.175) + (gross_annual - 53500) * 0.30
            else:
                tax = (15600 * 0.105) + (37900 * 0.175) + (24600 * 0.30) + (gross_annual - 78100) * 0.33

        # --- 7. SPAIN (ES) ---
        elif country == 'ES':
            # Seguridad Social (Worker contribution ~6.35%)
            social = min(gross_annual, 54000) * 0.0635
            
            # IRPF (Progressive tax brackets)
            taxable = max(0, gross_annual - 5550)
            if taxable <= 12450:
                tax = taxable * 0.19
            elif taxable <= 20200:
                tax = (12450 * 0.19) + (taxable - 12450) * 0.24
            elif taxable <= 35200:
                tax = (12450 * 0.19) + (7750 * 0.24) + (taxable - 20200) * 0.30
            else:
                tax = (12450 * 0.19) + (7750 * 0.24) + (15000 * 0.30) + (taxable - 35200) * 0.37

        # --- 8. FRANCE (FR) ---
        elif country == 'FR':
            # Cotisations salariales & CSG/CRDS (~21%)
            social = gross_annual * 0.21
            
            # Impôt sur le revenu (IR)
            taxable = max(0, (gross_annual - social) * 0.90)
            if taxable <= 11294:
                tax = 0.0
            elif taxable <= 28797:
                tax = (taxable - 11294) * 0.11
            else:
                tax = (17503 * 0.11) + (taxable - 28797) * 0.30

        # --- 9. GERMANY (DE) ---
        elif country == 'DE':
            # Sozialversicherung (KV, PV, RV, AV ~20%)
            social = min(gross_annual, 90600) * 0.20
            
            # Lohnsteuer (Grundfreibetrag ~€11,784)
            taxable = max(0, gross_annual - 11784)
            if taxable <= 0:
                tax = 0.0
            elif taxable <= 50000:
                tax = taxable * 0.25
            else:
                tax = (50000 * 0.25) + (taxable - 50000) * 0.42

        # --- 10. UAE (UNITED ARAB EMIRATES) ---
        elif country == 'UAE':
            # 0% personal income tax and 0% social contribution
            tax = 0.0
            social = 0.0

        # --- DEFAULT FALLBACK ---
        else:
            tax = gross_annual * 0.20 # Flat 20% estimate
            
        # Convert back to weekly values
        weekly_tax = tax / 52
        weekly_social = social / 52
        
        return round(weekly_tax, 2), round(weekly_social, 2)

    @staticmethod
    def get_tax_rate(settings):
        """
        Gets the applicable tax/VAT rate based on company settings.
        Returns a float (e.g., 0.20 for 20%)
        """
        vat_reg = settings.get('vat_registered', 'no')
        if vat_reg not in ['yes', 'on', 'true', '1']:
            return 0.0
            
        manual = settings.get('default_tax_rate')
        if manual and str(manual).strip() != '':
            try:
                return float(manual) / 100.0
            except ValueError:
                pass
                
        country = (settings.get('country_code') or 'UK').upper()
        # Default fallback standard VAT/GST/Sales tax rates
        TAX_RATES = {
            'UK': 0.20,   # 20% VAT
            'IE': 0.23,   # 23% VAT
            'US': 0.00,   # 0% base (varies by state/city)
            'CAN': 0.05,  # 5% GST
            'CA': 0.05,
            'AUS': 0.10,  # 10% GST
            'AU': 0.10,
            'NZ': 0.15,   # 15% GST
            'FR': 0.20,   # 20% TVA
            'DE': 0.19,   # 19% MwSt
            'ES': 0.21,   # 21% IVA
            'UAE': 0.05   # 5% VAT
        }
        return TAX_RATES.get(country, 0.20)

    @staticmethod
    def calculate_invoice_totals(settings, subtotal):
        """
        Calculates the tax amount and grand total.
        Returns (tax_rate, tax_amount, grand_total)
        """
        rate = TaxEngine.get_tax_rate(settings)
        tax_amount = subtotal * rate
        return rate, tax_amount, subtotal + tax_amount
