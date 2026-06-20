# Guía de uso de la plataforma Quantum Trading

## Qué es la plataforma
Quantum Trading es una plataforma de trading automatizado de criptomonedas en futuros. Permite configurar bots, recibir señales de IA basadas en ICT/SMC, operar en paper trading y gestionar cartera.

## Componentes principales
- **Bots**: estrategias automáticas configurables por símbolo, timeframe y riesgo.
- **Scanner de IA**: analiza pares cada 15 minutos y genera señales con score, tier y probabilidad.
- **Paper Trading**: simulación sin dinero real para validar estrategias.
- **Dashboard**: métricas de rendimiento, PnL, win rate, drawdown.
- **Shadow Mode**: evalúa modelos candidatos antes de promocionarlos a producción.

## Tiers de señal
- **STRONG**: score alto, confluencia fuerte, probabilidad elevada.
- **MODERATE**: score medio, condiciones razonables.
- **WEAK**: score bajo, mayor riesgo.

## Shadow Mode
El shadow mode compara el modelo live contra un candidato. `promote=false` significa que el candidato aún no supera los umbrales de Sharpe para reemplazar al live. Los umbrales son:
- candidate_sharpe > live_sharpe * 1.2
- candidate_sharpe > 0.5

## Anti-fake
El sistema anti-fake evalúa si una señal tiene características de falsa ruptura. Puede marcar señales como REAL o FAKE y bloquear entradas de baja calidad.

## Configuración de un bot
1. Ve a Bots → Nuevo bot.
2. Selecciona exchange, par y timeframe.
3. Ajusta capital por operación, stop loss, take profit y ratio riesgo/beneficio.
4. Activa paper trading primero para validar.
5. Cuando estés conforme, activa trading real.

## Bots y modos de activación
Un bot es un operador automatizado que escucha señales y ejecuta órdenes según tu configuración. Cada bot opera un único par (símbolo) en un timeframe específico.

### Crear un bot
1. Ve a Bots y pulsa "Nuevo bot".
2. Rellena el apartado Básico: nombre, símbolo, timeframe, apalancamiento.
3. Configura Capital / SL: tipo de sizing (porcentaje o fijo USDT) y stop loss inicial.
4. Define Take Profits (opcional pero recomendado).
5. En la pestaña Activación, elige cómo se disparará.

### Fuentes de activación
Cada bot puede tener una o varias fuentes activas simultáneamente. No es necesario elegir solo una.

#### Webhook externo
TradingView u otro sistema envía alertas JSON al endpoint del bot. Tú controlas cuándo se dispara desde fuera. Ideal si ya tienes indicadores propios en TradingView.

#### Scanner de IA interno
El bot se activa automáticamente cuando el scanner de IA genera una señal para el par y timeframe configurados.

#### Manual
El bot no se activa automáticamente. Puedes disparar señales manualmente desde la interfaz.
