# Guía de Usuario — Motor IA de Trading Bot Platform
**Fecha:** 2026-06-20
**Versión:** Scanner IA con panel expandido, Scanner Live, Dashboard IA, Monte Carlo, filtros configurables, sizing dinámico, circuit breaker, validación heurística, macro context, portfolio manager, chat y asistente.

---

## 1. ¿Qué es el Scanner IA?

El Scanner IA es un motor de análisis técnico automático que:

1. **Escanea cada 5 minutos** los pares que tengas en tu watchlist
2. **Analiza 200 velas** de cada par usando teoría ICT (Inner Circle Trader) + SMC (Smart Money Concepts)
3. **Genera señales** con puntos de entrada, stop loss y take profits calculados matemáticamente
4. **Evalúa la calidad** de cada señal con dos capas independientes:
   - **Confluence Score** (0-100): ¿cuántos factores técnicos convergen?
   - **Signal Quality / Anti-Fake** (heurístico): ¿el volumen, spread y liquidez confirman la señal?
   - **XGBoost Anti-Fake** (ML): ¿qué dice el modelo entrenado con datos históricos?

### Entendiendo las etiquetas

| Etiqueta | Significado | Qué indica |
|----------|-------------|------------|
| **STRONG** | Calidad ≥75 pts | Señal con múltiples confirmaciones |
| **MODERATE** | Calidad 50-74 pts | Señal con algunas confirmaciones |
| **WEAK** | Calidad <50 pts | Señal débil, pocos factores a favor |
| **CLEAR** | 0 red flags | Sin señales de advertencia |
| **CAUTION** | 1 red flag | Hay algo que no encaja (spread alto, volumen bajo…) |
| **BLOCK** | 2+ red flags | Señal descartada automáticamente |

> **BLOCK nunca se opera.** Es una protección automática del sistema.

---

## 2. Diferencia entre Backtest y Ejecución Real

### Backtest (pestaña en la página IA)
Muestra **todas las señales generadas** (STRONG, MODERATE, WEAK) y qué habría pasado si las hubieras operado. Sirve para analizar el histórico antes de tomar decisiones.

### Bot Activator (ejecución real)
Es el sistema que envía órdenes al exchange. **Por defecto solo opera STRONG + CLEAR**, pero ahora puedes configurarlo para incluir MODERATE y CAUTION si el histórico lo justifica.

**Regla de oro:** Revisa el backtest antes de activar tiers inferiores. Los números no mienten.

---

## 3. Cómo Configurar un Bot con Señales IA

### Paso 1: Crear/Editar un bot
Ve a **Bots → Nuevo bot** o edita uno existente.

### Paso 2: Seleccionar modo de activación
En la pestaña **Activación**, elige **Scanner IA** (icono 🤖).

### Paso 3: Configurar filtros

#### Tiers de calidad aceptados
- **STRONG** → Activado por defecto. Señales de mayor calidad.
- **MODERATE** → Opcional. Actívalo solo si el backtest muestra win rate >50%.
- **WEAK** → Opcional. Alto riesgo. Recomendado solo para paper trading.

#### Estados anti-fake aceptados
- **CLEAR** → Activado por defecto. Señal limpia.
- **CAUTION** → Opcional. Incluye señales con 1 advertencia. Usar con sizing reducido.

> ⚠️ **Recomendación:** Empieza con STRONG+CLEAR. Activa MODERATE solo después de ver 30+ señales en el backtest con buen resultado.

### Paso 4: Configurar sizing dinámico

El sizing dinámico te permite **reducir el tamaño de la posición** según la calidad de la señal:

| Configuración | Ejemplo conservador | Ejemplo agresivo |
|---------------|---------------------|------------------|
| STRONG | 100% | 100% |
| MODERATE | 50% | 80% |
| WEAK | 0% | 50% |
| CLEAR | 100% | 100% |
| CAUTION | 25% | 50% |

**Ejemplo práctico:**
- Tu bot está configurado con 100 USDT por operación.
- Llega una señal MODERATE + CLEAR.
- Tienes sizing MODERATE=50% y CLEAR=100%.
- **Resultado:** El bot abre la posición con 50 USDT (100 × 0.5 × 1.0).

> 💡 **Tip:** Si activas MODERATE o CAUTION, baja el sizing. Es mejor más señales pequeñas que pocas grandes y arriesgadas.

### Paso 5: Circuit breaker

El circuit breaker es un **seguro automático** que bloquea un tier si empiezas a perder repetidamente:

| Tier | Default | Qué significa |
|------|---------|---------------|
| STRONG | 3 SL seguidos | Si pierdes 3 veces seguidas con señales STRONG, ese tier se bloquea temporalmente |
| MODERATE | 2 SL seguidos | Más restrictivo porque el tier es más débil |
| WEAK | 1 SL seguido | Un solo SL y se bloquea |

**Características importantes:**
- Solo bloquea el tier afectado. El bot sigue operando otros tiers o modos.
- Se **auto-resetea después de 24 horas**.
- Puedes cambiar los umbrales en la configuración del bot.

### Paso 6: Score mínimo y concurrencia

- **Score mínimo:** Umbral del Confluence Score (0-100). Default: 60.
- **Máx. posiciones simultáneas:** Cuántas operaciones puede tener abiertas al mismo tiempo. Default: 1.

---

## 4. Dashboard de Validación Heurística

### Dónde encontrarlo
Ve a **IA → pestaña Validación** (icono 🛡️).

### Qué muestra
Es un informe estadístico que responde a la pregunta: **"¿Está funcionando bien el heurístico?"**

#### Matriz Tier × Status
Muestra para cada combinación (ej. STRONG+CLEAR, MODERATE+CAUTION):
- Cuántas señales se generaron
- Cuántas ya tienen resultado (resueltas)
- Cuántas fueron SUCCESS (ganadoras), FAILURE (perdedoras), EXPIRED (sin resultado en 50 velas)
- **Win rate:** % de acierto
- **Avg PnL %:** Beneficio/pérdida promedio

#### Cómo interpretar los colores
- **Barra verde (≥60% win rate):** El tier/status está funcionando bien.
- **Barra amarilla (45-59%):** Aceptable, pero usa sizing reducido.
- **Barra roja (<45%):** No operes este tier en vivo.

### Casos de uso

**Caso A: CAUTION tiene el mismo win rate que CLEAR**
→ El heurístico de red flags es demasiado conservador. Puedes activar CAUTION sin miedo.

**Caso B: MODERATE tiene win rate 55% y PnL positivo**
→ Vale la pena activar MODERATE con sizing del 50%.

**Caso C: WEAK tiene win rate 30% y PnL negativo**
→ Mantén WEAK desactivado o solo en paper trading.

**Caso D: STRONG tiene win rate 45%**
→ Revisa el mercado. Puede haber cambiado el régimen (tendencia lateral, alta volatilidad…).

---

## 5. Flujo Recomendado para Activar Tiers Inferiores

### Fase 1: Observación (1-2 semanas)
1. Mantén el bot en **STRONG + CLEAR** (default).
2. Activa **paper trading** (no dinero real).
3. Revisa la pestaña **Backtest** y **Validación** diariamente.

### Fase 2: Análisis
1. Si MODERATE muestra win rate >50% durante al menos 30 señales resueltas:
   - Activa MODERATE en paper trading.
   - Configura sizing MODERATE al 50%.
   - Circuit breaker MODERATE a 2 SL.

2. Si CAUTION muestra win rate similar a CLEAR:
   - Activa CAUTION en paper trading.
   - Configura sizing CAUTION al 25%.

### Fase 3: Migración a real
1. Después de 2 semanas de paper trading exitoso:
   - Cambia el bot a cuenta real.
   - Mantén los mismos parámetros.
   - No subas el sizing hasta tener 20+ operaciones reales exitosas.

### Fase 4: Optimización continua
1. Revisa la pestaña **Validación** semanalmente.
2. Si un tier baja de 50% win rate, desactívalo temporalmente.
3. Ajusta sizing según el PnL promedio.

---

## 6. Paper Trading vs Trading Real

### Paper Trading
- Simula operaciones con dinero ficticio.
- **Úsalo siempre** para probar nuevos tiers o configuraciones.
- En la configuración del bot, selecciona una cuenta **Paper** en lugar de **Real**.

### Trading Real
- Opera con dinero real en el exchange.
- **Nunca actives MODERATE/WEAK/CAUTION en real sin validar primero en paper.**

---

## 7. Macro Context (Contexto de Mercado)

El sistema ahora integra **funding rates** y **calendario económico** para evitar operar en ventanas de alto riesgo.

### Funding Rate
- Se muestra en la página IA, arriba del scanner.
- Si el funding es muy alto (>10% anualizado), el sistema marcará **CAUTION** o **AVOID**.
- Operar LONG cuando el funding es muy positivo es caro (pagas por mantener la posición).

### Eventos Económicos
- El sistema detecta eventos de alto impacto (FOMC, CPI, NFP) en las próximas horas.
- Si hay un evento importante en menos de 60 minutos, el sistema recomendará **CAUTION**.
- Los eventos aparecen como alertas amarillas/rojas en la barra de macro context.

---

## 8. Portfolio Manager (Gestión de Cartera)

El Portfolio Manager evalúa tu riesgo agregado antes de abrir cada posición.

### Límites configurables por bot
Ve a la configuración IA del bot, sección **Límites de exposición (Portfolio)**:

| Límite | Default | Qué hace |
|--------|---------|----------|
| Exposición total max | 50% | Bloquea nuevas entradas si ya tienes el 50% del equity en posiciones abiertas |
| Por símbolo max | 30% | Reduce sizing a la mitad si un símbolo supera el 30% del equity |
| Direccional max | 40% | Reduce sizing si todo tu lado (ej. LONG) supera el 40% |
| Alts LONG antes alerta | 3 | Si tienes 3+ alts en LONG y BTC está bajista HTF, reduce sizing |

### Widget en Dashboard
En el Dashboard verás un resumen de tu portfolio:
- Total en LONG / SHORT / NET
- Desglose por símbolo

---

## 9. XGBoost Anti-Fake — Explicado para Humanos

### 9.1 ¿Qué es XGBoost?
XGBoost es un **modelo de inteligencia artificial** (machine learning) que aprende de las señales pasadas para predecir si una señal nueva va a funcionar o va a fallar.

Piensa en él como un "experto virtual" que ha estudiado cientos de señales anteriores y aprendido patrones del tipo:
- "Cuando el volumen es bajo y el spread es alto, la señal suele fallar"
- "Las señales en horas de baja liquidez (3-5 AM UTC) tienen más probabilidad de ser falsas"

### 9.2 ¿Qué mide?
El modelo mide la **probabilidad de que una señal sea FAKE** (es decir, que termine en FAILURE).

Mira 15 características de cada señal:
1. Cuántos FVGs alineados hay
2. La distancia al Order Block (en ATRs)
3. Si hubo liquidity sweep
4. La posición en premium/discount
5. La hora UTC y día de la semana
6. Cuántos EQ highs/lows hay cerca
7. Ratio de volumen vs promedio
8. Spread relativo al ATR
9. El confluence score
10. El tipo de trigger (OB o FVG)
11. El bias (alcista o bajista)
12. Si el último break fue CHoCH o BOS

### 9.3 ¿Para qué sirve?
Tiene 3 usos principales:

1. **Validación cruzada**: Si el modelo predice >70% de probabilidad de fallo para una señal que el heurístico marcó como CLEAR, el sistema puede elevarla a CAUTION automáticamente.

2. **Feature importance**: Te dice qué variables históricamente predicen fallos. Por ejemplo, puede descubrir que operar a las 2 AM UTC en altcoins con volumen <0.5× es una receta para perder.

3. **Ajuste de umbrales**: Con datos reales de miles de señales, el modelo puede sugerir cambios en los pesos del motor heurístico.

### 9.4 ¿Cuándo está activo?
El modelo necesita **mínimo 200 señales resueltas** (SUCCESS o FAILURE) para entrenarse. Hasta entonces, el sistema funciona 100% con el motor heurístico (Signal Quality Engine).

- Se entrena **automáticamente los domingos a las 03:00 UTC**.
- También puedes pulsar **"Reentrenar ahora"** en la pestaña Scanner.
- En la UI verás: "Datos XGBoost: ✓ Listo" (si tiene ≥200 muestras) o "127 / 200" (si aún le faltan).

### 9.5 ¿XGBoost reemplaza el motor heurístico?
**NO.** Son dos capas que trabajan juntas:
- **Heurístico** (activo siempre): reglas interpretables que cualquier humano puede entender
- **XGBoost** (activo tras ≥200 muestras): capa ML que detecta patrones no obvios

Piensa en el heurístico como el cinturón de seguridad (siempre puesto) y XGBoost como el asistente de conducción (mejora con experiencia).

---

## 10. Entendiendo el Backtest — Respuestas a tus Dudas

### 10.1 ¿Qué son las "R"?
**R = Unidad de Riesgo (Risk).** 1R es la distancia desde tu punto de entrada hasta tu Stop Loss.

**Ejemplo:**
- Entras en LONG en BTC a 100,000 USDT
- Tu SL está en 99,000 USDT
- Tu riesgo = 1,000 USDT = **1R**
- Si pierdes y el precio te saca por SL: **-1R**
- Si ganas y el precio llega a TP1 (a 101,500): **+1.5R**

El sistema usa **R para que todas las operaciones sean comparables**, independientemente del par o el precio. Una pérdida de -1R en BTC es equivalente a una pérdida de -1R en DOGE en términos de gestión de riesgo.

### 10.2 ¿Qué es "Bars Promedio"?
Es el **número promedio de velas** que tarda una señal en resolverse (llegar a TP1, SL, o expirar).

- **Bars promedio = 1** → La mayoría de señales se resuelven en la siguiente vela
- **Bars promedio = 2** → Tardan 2 velas de media

**Para qué sirve:** Te dice qué tan "lenta" es la estrategia. Si el bars promedio es alto (ej. 20), las señales tardan mucho en resolverse y tu capital está "bloqueado" más tiempo.

### 10.3 ¿Por qué Win Rate 100% puede tener P&L negativo?
Esta es tu duda más importante. Veamos tu ejemplo:

```
DATOS DE STRONG:
Resueltas: 1
Win Rate: 100%
P&L simulado: -1.7R
```

**Esto es matemáticamente inconsistente.** Si hay 1 señal resuelta y el Win Rate es 100%, significa que esa única señal fue SUCCESS (ganó). Una señal SUCCESS debe tener P&L positivo porque el precio tocó TP1 antes que SL.

**¿Por qué puede aparecer negativo? Hay varias explicaciones técnicas:**

1. **Bug de visualización en el frontend**: El P&L simulado agregado puede estar usando un valor por defecto (fallback) cuando `pnl_pct` es null, o puede estar sumando señales que no deberían estar en ese filtro.

2. **Tie-breaker del Outcome Tracker**: Cuando en la misma vela se tocan TP1 y SL a la vez, el sistema usa el cierre de la vela (close) para decidir si es SUCCESS o FAILURE. Si el close está a favor pero el precio real de salida fue peor, puede haber una discrepancia.

3. **Niveles invertidos (INVALID)**: Una señal podría haber sido marcada como SUCCESS pero con niveles mal calculados, resultando en P&L negativo.

> **Recomendación**: Si ves esto consistentemente, reporta un bug. Con 1 señal y 100% WR, el P&L DEBE ser positivo.

### 10.4 ¿Por qué Win Rate 95% tiene P&L -58.4R?
Tu ejemplo de MODERATE:
```
Resueltas: 57
Win Rate: 95%
P&L simulado: -58.4R
```

Esto **SÍ es posible matemáticamente**, aunque parezca contraintuitivo. La clave está en que **Win Rate no lo es todo**.

**El sistema usa R:R fijo:**
- TP1 = 1.5R (si ganas, ganas 1.5 unidades de riesgo)
- SL = 1.0R (si pierdes, pierdes 1.0 unidad de riesgo)

**Punto de equilibrio teórico**: Necesitas ~40% de acierto para ser rentable (porque 1.5 > 1.0). Con 95% deberías estar muy rentable.

**¿Por qué entonces es negativo?**

1. **Slippage y gaps**: El Outcome Tracker usa precios OHLCV de Binance. Si hay un gap (el precio salta de 100 a 98 sin pasar por 99), tu SL real puede ejecutarse a -2R en lugar de -1R. En cripto, especialmente en alts de baja capitalización, los gaps son comunes.

2. **Velas con mechas extremas**: Una vela puede tener `low` muy lejano por un instante (liquidación en cascada), tocar tu SL en -3R, y luego recuperarse. El tracker registra ese `low` como el precio de salida.

3. **EXPIRED no cuenta en WR pero sí en P&L**: Las señales EXPIRED (50 velas sin tocar nada) no entran en el cálculo de Win Rate, pero algunas implementaciones del frontend podrían estar asignándoles un P&L negativo implícito (tiempo de capital comprometido).

4. **R:R real ≠ R:R teórico**: Si el Confluence Engine calculó TP1 a 1.5R pero por la volatilidad del par el precio real de take profit se ejecutó a 1.2R, y las pérdidas se ejecutaron a 1.8R por slippage, el sistema pierde aunque gane más veces.

**Fórmula simple**:
```
P&L total = (Ganadoras × avg win) - (Perdedoras × avg loss)

Si 54 ganaron +1.2R de media = +64.8R
Y 3 perdieron -18.0R de media = -54.0R  (por gaps/slippage en alts volátiles)
P&L total = +10.8R  (debería ser positivo)

PERO si las 3 perdedoras perdieron -40R cada una por un flash crash:
P&L total = 64.8 - 120 = -55.2R  (negativo a pesar de 95% WR)
```

**Conclusión**: Un Win Rate alto con P&L negativo indica que tus **pérdidas están siendo mucho mayores de lo previsto** (gaps, slippage, flash crashes). Esto suele pasar en:
- Altcoins de baja capitalización
- Timeframes muy bajos (1m, 5m)
- Periodos de alta volatilidad

### 10.5 Explicación columna por columna del Backtest

```
Fecha       Par      TF   Dir.  Score  ADX    Tier   HTF  Outcome   P&L
10/5 00:03  FARTCOIN 15m  ↑L    26     27     WEAK   ↑    ·         —
10/5 00:03  BTC      1h   ↑L    43     23≈R   WEAK   ↑    SUCCESS   -0.57%
10/5 00:03  ETH      1h   ↑L    39     15≈R   WEAK   ↑    SUCCESS   +0.69%
10/5 00:03  XAUT     1h   ↑L    26     11≈R   WEAK   ↑    ·         —
10/5 00:02  ONDO     15m  ↑L    45     12≈R   WEAK   ↑    ·         —
10/5 00:02  DOGE     15m  ↓S    27     16≈R   WEAK   ↓    SUCCESS   -3.01%
```

| Columna | Significado | Ejemplo |
|---------|-------------|---------|
| **Fecha** | Momento en que se generó la señal | 10/5 00:03 = 10 de mayo, 00:03 UTC |
| **Par** | Par de trading | BTC, ETH, DOGE… |
| **TF** | Timeframe (temporalidad) | 15m, 1h, 4h… |
| **Dir.** | Dirección de la señal | ↑L = LONG (alcista), ↓S = SHORT (bajista) |
| **Score** | Confluence Score (0-100) | 43 = puntuación de convergencia técnica |
| **ADX** | Valor del ADX (fuerza de tendencia) | 23 ≈ R significa ADX≈23 y mercado en Rango (Ranging) |
| **Tier** | Calidad de la señal (STRONG/MODERATE/WEAK) | WEAK = señal débil |
| **HTF** | Bias del timeframe superior | ↑ = HTF alcista, ↓ = HTF bajista, → = neutral |
| **Outcome** | Resultado de la señal | SUCCESS = ganó, FAILURE = perdió, · = aún pendiente, EXPIRED = sin resolución |
| **P&L** | Profit & Loss en porcentaje | +0.69% = ganancia, -3.01% = pérdida, — = aún no resuelta |

**Notas importantes sobre lo que ves:**

- **SUCCESS con P&L negativo** (BTC: SUCCESS -0.57%): Esto puede pasar por el tie-breaker (TP1 y SL tocados en la misma vela) o por slippage. En teoría no debería ocurrir, pero en la práctica los gaps lo causan.

- **"·" en Outcome**: La señal aún está PENDIENTE. El Outcome Tracker revisa cada 15 minutos.

- **"≈R" junto al ADX**: Indica que el mercado está en rango (Ranging), no en tendencia. El ADX es <25, por lo que el peso de algunos factores (sweep, killzone) se reduce.

### 10.6 Diferencia entre P&L en % y P&L en R

- **P&L %**: Es el resultado real de la operación en porcentaje respecto al capital comprometido. Ej: +0.69% significa que si arriesgaste 100 USDT, ganaste 0.69 USDT.
- **P&L en R**: Es el resultado en unidades de riesgo. Ej: +1.5R significa que ganaste 1.5 veces lo que arriesgaste.

**Relación**: Normalmente 1R ≈ el % que configuras como riesgo por operación. Si arriesgas 1% por operación, entonces +1.5R ≈ +1.5%.

---

## 11. Preguntas Frecuentes

### ¿Por qué el bot no opera aunque veo señales en el backtest?
El backtest muestra **todas** las señales. El bot solo opera las que cumplan sus filtros configurados. Revisa:
- ¿El par está en tu watchlist?
- ¿El tier de la señal está en `allowed_tiers` del bot?
- ¿El status está en `allowed_statuses`?
- ¿El circuit breaker está abierto para ese tier?
- ¿El bot tiene posiciones abiertas y ya alcanzó `max_concurrent`?
- ¿El macro context está bloqueando ese par en este momento?

### ¿Puedo tener varios bots con diferentes configuraciones para el mismo par?
Sí. Puedes tener:
- Bot A: STRONG+CLEAR, sizing 100%, cuenta real
- Bot B: STRONG+MODERATE+CAUTION, sizing 50%, paper trading

### ¿Qué pasa si edito un bot que está activo?
El sistema te pedirá que pauses el bot antes de editarlo. Esto evita que cambies la configuración a mitad de una operación.

### ¿Por qué no puedo incluir BLOCK?
BLOCK significa 2 o más red flags (spread excesivo, volumen anómalo, etc.). Es una protección de seguridad del sistema. Si crees que el heurístico es demasiado restrictivo, revisa el dashboard de Validación: si BLOCK tenía muchas señales buenas, podemos ajustar los pesos del anti-fake en futuras versiones.

### ¿Cómo sé si el circuit breaker se ha activado?
1. En los logs del bot verás: "circuit breaker OPEN for tier MODERATE"
2. En `ai_signal_config` del bot aparecerá `circuit_breaker_state.MODERATE.tripped_at`
3. Se resetea automáticamente a las 24h. También puedes editar el bot (pausándolo) para forzar el reset manual si cambias algún parámetro.

### ¿El sizing dinámico afecta el apalancamiento?
No. El sizing afecta la **cantidad de capital** que usa la posición. El apalancamiento se mantiene según lo configurado en el bot. Ejemplo:
- Capital configurado: 100 USDT
- Sizing MODERATE: 50%
- Apalancamiento: 10x
- Resultado: 50 USDT de margen × 10 = posición de 500 USDT

### ¿Por qué veo señales con Outcome "·" (punto) hace horas?
El Outcome Tracker revisa cada 15 minutos, pero solo procesa señales que tengan al menos **1 vela completa** de antigüedad. Si acabas de lanzar el sistema, las primeras señales pueden tardar en aparecer con outcome. También, si el fetch de velas de Binance falla, la señal permanece PENDING hasta el próximo ciclo.

### ¿Qué es Scanner Live y para qué sirve?
Es una pestaña dentro de IA Engine que muestra el escaneo del mercado en tiempo real: pares analizados, señales generadas, rechazos y KPIs de las últimas 24h. Úsala para entender por qué no llegan señales o para verificar que el motor está activo.

### ¿Por qué un par aparece como PAUSED en el Deployment Gate?
Ese par/timeframe tiene métricas muy degradadas (win rate bajo, drawdown alto o feature drift importante). El sistema lo pausa automáticamente para bots reales como protección. Puedes seguir viéndolo en paper trading.

### ¿Qué significa que el AUC del modelo sea 0.5?
Un AUC de 0.5 indica que el modelo no distingue mejor que el azar entre señales buenas y malas. Normalmente ocurre cuando hay muy pocas muestras o el mercado cambió drásticamente. Espera más señales o revisa el feature drift.

### ¿Puedo usar Monte Carlo sin ser administrador?
El módulo Monte Carlo requiere el rol `moderator` o `admin`. Si no lo tienes, solicítalo al administrador de la plataforma.

### ¿El asistente de IA puede ver mis posiciones?
No. El asistente responde preguntas generales sobre el uso de la plataforma, pero no tiene acceso a tus posiciones, balances ni datos de mercado en tiempo real. No proporciona recomendaciones de inversión.

### ¿Por qué mi rol no ve el menú de IA Engine?
El motor IA y Monte Carlo están restringidos a `moderator` y `admin`. Los usuarios con rol `rol1` tienen acceso a funcionalidades básicas como paper trading, chat y señales de trading. Contacta al administrador si necesitas más permisos.

---

## 12. Glosario Rápido

| Término | Significado |
|---------|-------------|
| **BOS** | Break of Structure — ruptura de estructura a favor de la tendencia |
| **CHoCH** | Change of Character — ruptura en contra de la tendencia, posible reversión |
| **OB** | Order Block — zona institucional donde entraron grandes jugadores |
| **FVG** | Fair Value Gap — gap de precio dejado por un impulso fuerte |
| **HTF** | Higher Time Frame — timeframe superior (ej. 4h para un análisis en 1h) |
| **Killzone** | Ventanas horarias de alta liquidez (London, NY, Asian) |
| **PnL** | Profit and Loss — beneficio o pérdida de una operación |
| **SL** | Stop Loss — límite de pérdida automático |
| **TP** | Take Profit — objetivo de beneficio |
| **R** | Risk — unidad de riesgo (distancia entry→SL) |
| **Bars** | Velas — cada barra del gráfico |
| **ADX** | Average Directional Index — fuerza de la tendencia |
| **Sweep** | Liquidity Sweep — mecha que rompe un nivel y vuelve (fake-out) |
| **P/D** | Premium/Discount — posición del precio en el rango reciente |

---

## 13. Checklist antes de activar IA en un bot

- [ ] Tienes el rol adecuado (`moderator` o `admin`) para usar el motor IA.
- [ ] El par está en la watchlist de IA.
- [ ] La cuenta (real o paper) está configurada.
- [ ] El bot está pausado mientras configuras.
- [ ] Has revisado el backtest del par en el timeframe elegido (panel expandido).
- [ ] Has revisado el dashboard de Validación (últimos 30 días).
- [ ] Has consultado el Scanner Live para confirmar que el par se escanea correctamente.
- [ ] Has revisado el Deployment Gate: el par/timeframe no está en estado PAUSED.
- [ ] Has revisado las métricas del Dashboard IA (AUC, win rate, divergencia paper/real).
- [ ] Los tiers activados tienen win rate >50%.
- [ ] El sizing está ajustado para tiers inferiores.
- [ ] Los circuit breakers están configurados.
- [ ] Has revisado el Macro Context (funding rates, eventos).
- [ ] Has configurado los límites del Portfolio Manager.
- [ ] Has guardado la configuración.
- [ ] Has activado el bot y verificado que aparece en "Bots IA activos".

---

## 14. Panel Expandido del Scanner

Al pulsar cualquier caja del scanner se abre un **panel anclado debajo del grid** en lugar de un modal. Esto permite seguir navegando por la watchlist sin perder el contexto del par seleccionado.

### 14.1 Pestaña Detalle

Muestra el **gráfico de velas en tiempo real** con el análisis ICT/SMC superpuesto:

- Zona de entrada, stop loss y take profits de la señal actual.
- Order Blocks, Fair Value Gaps, EQ highs/lows y liquidity sweeps detectados.
- Confluence Score, tier, anti-fake status y bias del timeframe superior.
- Contexto textual que resume por qué se generó la señal.

> El gráfico permanece montado al cambiar de pestaña, por lo que no se recarga al volver a Detalle.

### 14.2 Pestaña Backtest

Resumen ejecutivo del par seleccionado:

- Total de señales generadas y cuántas ya tienen resultado.
- Win rate y PnL promedio.
- Tabla plegable con el histórico completo filtrado por ese par.

Úsala para decidir si activar tiers inferiores **solo para ese par**.

### 14.3 Pestaña Validación

Matriz Tier × Status filtrada por el par seleccionado:

- Win rate y PnL promedio por combinación (STRONG+CLEAR, MODERATE+CAUTION, etc.).
- Selector de ventana temporal: 7, 30 o 90 días.

Si ves que una combinación tiene buena estadística en el backtest general pero mala solo para este par, reconsidera operar ese par en concreto.

---

## 15. Scanner Live

La pestaña **Live** del IA Engine muestra el **escaneo del mercado en tiempo real**. Es útil para entender qué está haciendo el motor ahora mismo y por qué no se generan señales.

### 15.1 Eventos en vivo

Cada vez que el scanner analiza un par, publica un evento con:

- Par y timeframe analizados.
- Resultado: señal generada, rechazada o sin oportunidad.
- Motivo del rechazo (por ejemplo: gate de riesgo, macro context, deployment gate pausado, score insuficiente).
- Timestamp del evento.

### 15.2 KPIs de las últimas 24h

- **Pares escaneados:** cuántos pares de tu watchlist ha revisado el sistema.
- **Señales generadas:** total de señales en las últimas 24 horas.
- **Rechazos:** cuántas señales no pasaron los filtros de riesgo o calidad.
- **Tiempo desde último scan:** si pasa mucho tiempo, puede haber un problema de conectividad o el mercado está sin oportunidades.

### 15.3 Consejos del asistente local

Si tienes configurado Ollama, el Scanner Live puede mostrar **tips generados por un modelo local** que resumen el estado del mercado y sugieren ajustes simples (por ejemplo: "el par está en rango, considera reducir sizing"). Son orientativos, no recomendaciones de inversión.

### 15.4 Cómo usarlo

1. Abre **IA → Live**.
2. Observa si los pares de tu watchlist se escanean cada 5 minutos.
3. Si esperabas una señal y no aparece, revisa el motivo de rechazo: a veces el sistema está protegiendo tu capital.
4. Si ves muchos rechazos seguidos por el mismo motivo, revisa la configuración del bot o el dashboard de salud del modelo.

---

## 16. Dashboard IA — Cómo interpretar las métricas

La pestaña **Dashboard** del IA Engine resume la salud del motor. No es necesario entender todas las métricas, pero sí las más importantes.

### 16.1 Métricas del modelo

| Métrica | Qué mide | Valor saludable | Qué hacer si baja |
|---------|----------|-----------------|-------------------|
| **AUC-ROC** | Capacidad del modelo para distinguir señales buenas de malas. | > 0.65 | Si cae cerca de 0.50, el modelo no distingue mejor que el azar. Revisa feature drift o espera más datos. |
| **Accuracy** | Porcentaje de señales clasificadas correctamente por el modelo. | Depende del balance; úsala junto a AUC. | Una accuracy muy alta con pocos datos puede ser sobreajuste. |
| **Muestras** | Cuántas señales resueltas tiene el modelo para entrenar. | ≥ 200 | Por debajo de 200 el modelo no está activo; se usa solo el heurístico. |

### 16.2 Métricas de rendimiento

| Métrica | Qué mide | Cómo interpretarla |
|---------|----------|--------------------|
| **Win Rate señales** | % de señales de backtest que terminaron en TP1. | > 50% es positivo si el R:R es favorable. |
| **Win Rate trades reales** | % de trades ejecutados por IA que ganaron. | Puede diferir del backtest por slippage, gaps y rechazos de órdenes. |
| **PnL acumulado IA real** | Beneficio/pérdida de los trades reales ejecutados por IA. | Negativo en corto plazo no invalida el sistema; mira el sample size. |
| **Sharpe** | Rentabilidad ajustada por volatilidad. | > 1 es aceptable; > 2 es bueno. |
| **Profit Factor** | Ganancias totales / pérdidas totales. | > 1.5 indica que las ganancias superan las pérdidas. |
| **Expectancy** | Ganancia/pérdida esperada por trade. | > 0 significa que, en promedio, cada trade aporta. |
| **Max Drawdown** | Caída máxima desde el pico de equity. | Cuanto más bajo, mejor. Si supera tu límite de riesgo, reduce sizing. |

### 16.3 Métricas de salud y calibración

- **Feature Drift:** indica si las características del mercado actual son diferentes a las del período de entrenamiento. Valores altos sugieren que el modelo puede necesitar recalibración.
- **Confidence Decay:** compara la confianza del modelo con el win rate real. Si predice 70% de éxito pero solo gana 40%, el modelo está sobreconfiado.
- **Model Decay:** velocidad a la que el modelo pierde precisión. Ayuda a estimar cuándo será necesario un nuevo entrenamiento.
- **Divergencia Paper/Real:** diferencia de rendimiento entre simulación y ejecución real. Una divergencia grande indica problemas de ejecución (slippage, lag, gaps).

### 16.4 Shadow Mode y Deployment Gate

- **Shadow Mode:** compara en vivo el modelo actual (live) con un modelo candidato. Si el candidato supera al live en Sharpe durante suficientes señales, puede promocionarse automáticamente.
- **Deployment Gate:** máquina de estados por par/timeframe. Estados:
  - **HEALTHY:** el par/timeframe puede operar en real.
  - **CAUTION:** métricas degradadas; reduce sizing o pásate a paper.
  - **PAUSED:** el par/timeframe está pausado para bots reales por malas métricas.

> El gate actúa por símbolo. Un par pausado no afecta a otros pares de tu watchlist.

### 16.5 Embudo de señales

Visualiza el recorrido de las señales en 30 días:

```
Generadas → Evaluadas → Aprobadas → Ejecutadas → Ganadas
```

Si muchas señales se pierden en "Aprobadas", los filtros de calidad o los gates de riesgo son muy restrictivos. Si se pierden en "Ejecutadas", revisa la configuración de los bots o la salud de las cuentas de exchange.

---

## 17. Monte Carlo

El módulo **Monte Carlo** permite diseñar estrategias propias, backtestearlas y evaluar su robustez mediante simulaciones. Está disponible para usuarios con rol `moderator`.

### 17.1 Crear una estrategia

Una estrategia se define mediante parámetros configurables:

- Par y timeframe.
- Condiciones de entrada y salida.
- Stop loss, take profits y apalancamiento.
- Tamaño de posición.

El editor incluye una plantilla que puedes adaptar a tu idea de trading.

### 17.2 Backtest

El backtest ejecuta la estrategia sobre datos históricos y genera:

- Curva de equity.
- Lista de trades con entrada, salida, PnL y duración.
- Métricas agregadas: win rate, profit factor, Sharpe, max drawdown, expectancy.

Revisa la curva de equity: busca una línea relativamente estable, no un pico seguido de una caída grande.

### 17.3 Simulaciones

Las simulaciones de Monte Carlo evalúan qué tan robusta es la estrategia ante distintos escenarios:

- **Return shuffle:** reordena los retornos para ver si el resultado depende de un orden específico.
- **Bootstrap:** remuestrea trades con reemplazo para estimar intervalos de confianza.
- **Perturbación de parámetros:** cambia ligeramente los parámetros para ver si la estrategia es sensible.
- **Equity path:** genera múltiples caminos posibles del capital.

### 17.4 Score de Monte Carlo

El score resume la calidad de la estrategia considerando rentabilidad, riesgo y robustez. No es una garantía, pero ayuda a descartar estrategias frágiles antes de arriesgar capital real.

> Usa Monte Carlo en **paper trading** antes de pasar a real, incluso si el backtest inicial es muy positivo.

---

## 18. Roles y permisos

La plataforma utiliza tres roles diferenciados:

### 18.1 `rol1` (Usuario estándar)

- Acceso a chat, paper trading, optimizador básico y señales de trading.
- No puede crear bots con motor IA ni usar Monte Carlo.
- No puede acceder a funciones de administración.

### 18.2 `moderator`

- Todo lo de `rol1`.
- Puede usar el **motor IA** (scanner, backtest, dashboard, bots IA).
- Puede acceder al **módulo Monte Carlo**.
- Puede gestionar bots avanzados y ver métricas de rendimiento.

### 18.3 `admin`

- Todo lo de `moderator`.
- Gestión de usuarios: crear, editar roles, resetear contraseñas.
- Acceso al **panel de administración del sistema**.
- Uso del **kill switch** de emergencia para cerrar todas las posiciones y pausar todos los bots.

> El rol determina qué opciones aparecen en el menú lateral. Si no ves una sección, consulta con el administrador.

---

## 19. Chat

La plataforma incluye un **chat interno** para comunicación en tiempo real.

### 19.1 Salas

- Salas públicas y privadas.
- Salas por tema (por ejemplo: operativa, alertas, soporte).
- Mensajes en tiempo real mediante WebSocket.

### 19.2 Mensajes privados

Puedes enviar mensajes directos a otros usuarios. Aparecen en una sala privada separada.

### 19.3 Menciones y reacciones

- Usa `@usuario` para llamar la atención de alguien.
- Reacciona a mensajes con emojis.
- Selector de color de fuente y soporte para GIFs.

---

## 20. Asistente de IA

El **Asistente** es un widget flotante que responde preguntas sobre el uso de la plataforma.

### 20.1 Qué puede hacer

- Explicar conceptos como tiers, circuit breaker, R, backtest o deployment gate.
- Guiarte en la creación de bots y la configuración del motor IA.
- Responder dudas sobre métricas y paneles.

### 20.2 Requisitos

- El asistente usa un modelo de lenguaje local a través de **Ollama**.
- Debe estar configurado el puente `ollama-bridge` en `docker-compose.yml` o el modelo debe ser accesible desde los contenedores.
- Si no hay modelo disponible, el widget no responde o muestra un mensaje de error.

### 20.3 Limitaciones

- El asistente no tiene acceso a tus posiciones ni a datos de mercado en tiempo real.
- No proporciona recomendaciones de inversión.
- Sus respuestas son orientativas; siempre verifica la configuración antes de operar.

---

## 21. Página de Documentación

Accede a **Docs** en el menú lateral para ver la guía completa paso a paso.

Incluye:
- Cómo empezar desde cero
- Configuración de exchanges y paper trading
- Creación de bots (webhook, indicador, IA)
- Explicación detallada del Motor IA
- Configuración avanzada (sizing, circuit breaker, portfolio)
- FAQ y solución de problemas

---

*Fin de la guía de usuario actualizada.*
