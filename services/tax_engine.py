# --- services/tax_engine.py ---

class TaxEngine:
    """
    Professional Estimate Engine for Multi-Country Payroll.
    Calculates Tax, Social Security/NI, and Net Pay estimates.
    """
    
    @staticmethod
    def calculate(gross_weekly, country_code):
        gross_annual = gross_weekly * 52
        tax = 0.0
        social = 0.0 
        
        # --- 1. UNITED KINGDOM (UK) ---
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
        elif country_code == 'IE':
            # USC (Universal Social Charge) - Blended est 3%
            if gross_annual > 13000: social += (gross_annual * 0.03)
            # PRSI (Pay Related Social Insurance) - Approx 4%
            social += (gross_annual * 0.04)
            
            # Income Tax (20% Standard Band up to €42k)
            taxable = gross_annual 
            if taxable > 42000:
                tax = (42000 * 0.20) + ((taxable - 42000) * 0.40)
            else:
                tax = taxable * 0.20

        # --- 4. AUSTRALIA (AUS) ---
        elif country_code == 'AUS':
            # Medicare Levy (2%)
            social = gross_annual * 0.02
            
            # Resident Tax Rates
            if gross_annual > 18200:
                if gross_annual < 45000: tax = (gross_annual - 18200) * 0.19
                elif gross_annual < 120000: tax = 5092 + (gross_annual - 45000) * 0.325
                else: tax = 29467 + (gross_annual - 120000) * 0.37

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
                
        country = settings.get('country_code', 'UK')
        # Default fallback rates if not set manually
        TAX_RATES = {
            'UK': 0.20,  'IE': 0.23,  'US': 0.00,  
            'CAN': 0.05, 'AUS': 0.10, 'NZ': 0.15,  
            'FR': 0.20,  'DE': 0.19,  'ES': 0.21   
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
