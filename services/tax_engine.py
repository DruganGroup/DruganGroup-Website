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