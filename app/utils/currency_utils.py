def format_currency(amount: float, currency: str = "THB") -> str:
    """แปลง 387500 -> '387,500.00 THB'"""
    if amount is None: return "0.00 " + currency
    return f"{amount:,.2f} {currency}"

def calculate_variance_pct(actual: float, expected: float) -> float:
    """คำนวณ % Diff ป้องกัน error div by zero"""
    if expected == 0:
        return 0.0 if actual == 0 else 100.0
    return round(((actual - expected) / expected) * 100, 2)