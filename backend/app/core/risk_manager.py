"""
Cálculos de precios de Stop Loss y Take Profit.
Funciones puras — sin efectos secundarios, sin acceso a DB ni exchanges.
"""
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP
import math


def _round_price(price: Decimal) -> Decimal:
    """
    Redondea el precio a una precisión adecuada según su magnitud.
    Mantiene 4 cifras significativas para que el exchange pueda usar
    su propio price_to_precision sin perder sentido económico.
    """
    if price <= 0:
        return price
    # Número de decimales necesarios para 4 cifras significativas
    magnitude = math.floor(math.log10(float(price)))
    decimal_places = max(0, 4 - magnitude - 1)
    quant = Decimal(10) ** -decimal_places
    return price.quantize(quant, rounding=ROUND_HALF_UP)


def calculate_sl_price(
    entry_price: Decimal,
    side: str,
    sl_percentage: Decimal,
) -> Decimal:
    """
    Calcula el precio de Stop Loss dado un % desde la entrada.

    Long: SL = entry * (1 - sl_pct/100)
    Short: SL = entry * (1 + sl_pct/100)
    """
    factor = sl_percentage / Decimal("100")
    if side == "long":
        price = entry_price * (Decimal("1") - factor)
    else:
        price = entry_price * (Decimal("1") + factor)
    return _round_price(price)


def calculate_tp_price(
    entry_price: Decimal,
    side: str,
    profit_percent: Decimal,
) -> Decimal:
    """
    Calcula el precio de Take Profit dado un % desde la entrada.

    Long: TP = entry * (1 + profit_pct/100)
    Short: TP = entry * (1 - profit_pct/100)
    """
    factor = profit_percent / Decimal("100")
    if side == "long":
        price = entry_price * (Decimal("1") + factor)
    else:
        price = entry_price * (Decimal("1") - factor)
    return _round_price(price)


def calculate_breakeven_price(
    entry_price: Decimal,
    side: str,
    lock_profit: Decimal,
) -> Decimal:
    """
    Precio al que mover el SL para asegurar breakeven + lock_profit.
    lock_profit = % adicional sobre la entrada a proteger.
    """
    return calculate_tp_price(entry_price, side, lock_profit)


def calculate_trailing_sl(
    current_peak: Decimal,
    side: str,
    callback_rate: Decimal,
) -> Decimal:
    """
    Calcula el nuevo precio de SL para un trailing stop.

    Long: SL = peak * (1 - callback/100)
    Short: SL = peak * (1 + callback/100)
    """
    factor = callback_rate / Decimal("100")
    if side == "long":
        price = current_peak * (Decimal("1") - factor)
    else:
        price = current_peak * (Decimal("1") + factor)
    return _round_price(price)


def should_move_trailing_sl(
    current_sl: Decimal,
    new_sl: Decimal,
    side: str,
) -> bool:
    """
    El trailing SL solo se mueve si mejora la protección
    (nunca se mueve en contra del trader).
    """
    if side == "long":
        return new_sl > current_sl
    else:
        return new_sl < current_sl
