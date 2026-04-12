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


def calculate_dynamic_sl_price(
    entry_price: Decimal,
    side: str,
    sl_percentage: Decimal,
    step_percent: Decimal,
    steps_taken: int,
) -> Decimal:
    """
    Calcula el precio de SL para el stop dinámico por pasos.

    Cada step mueve el SL step_percent% a favor del trader desde la entrada.
    Con N pasos dados:
      Long:  SL = entry * (1 - sl_pct/100 + steps_taken * step_pct/100)
      Short: SL = entry * (1 + sl_pct/100 - steps_taken * step_pct/100)

    El SL nunca puede cruzar la entrada en dirección adversa.
    """
    sl_factor   = sl_percentage  / Decimal("100")
    step_factor = step_percent   / Decimal("100") * steps_taken

    if side == "long":
        price = entry_price * (Decimal("1") - sl_factor + step_factor)
        # El SL no puede subir por encima de la entrada (protección)
        price = min(price, entry_price * Decimal("0.9999"))
    else:
        price = entry_price * (Decimal("1") + sl_factor - step_factor)
        # El SL no puede bajar por debajo de la entrada (protección)
        price = max(price, entry_price * Decimal("1.0001"))

    return _round_price(max(price, Decimal("0.0001")))


def get_dynamic_sl_step(
    entry_price: Decimal,
    current_price: Decimal,
    side: str,
    step_percent: Decimal,
) -> int:
    """
    Devuelve cuántos pasos de step_percent% se han completado
    en la dirección favorable desde la entrada.
    """
    if step_percent <= 0 or entry_price <= 0:
        return 0
    if side == "long":
        move = (current_price - entry_price) / entry_price * Decimal("100")
    else:
        move = (entry_price - current_price) / entry_price * Decimal("100")

    if move <= 0:
        return 0
    return int(move / step_percent)
