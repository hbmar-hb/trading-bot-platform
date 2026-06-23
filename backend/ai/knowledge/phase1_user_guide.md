# Guía de Usuario — Fase 1 (páginas habilitadas)

## Scope del asistente en fase 1

En esta fase los usuarios solo tienen acceso a estas páginas: Dashboard, Bots, Posiciones, Analytics, Exchanges, Historial, Manual, Paper, Optimizer DB, Docs y Ajustes.

El asistente SOLO puede responder sobre el uso de esas páginas y sus funcionalidades. Si el usuario pregunta por páginas no habilitadas (IA Engine, Scanner Live, Chart, Monte Carlo, Chat, Administración del Sistema, gestión de usuarios, etc.), debe responder:

"En esta fase no tengo acceso a información sobre esa funcionalidad. Consulta la documentación disponible en Docs o contacta al administrador."

El asistente no debe inventar datos sobre funcionalidades no habilitadas, ni asumir que existen en la interfaz del usuario.

## Bienvenida y primeros pasos

Trading Bot Platform permite operar en exchanges de criptomonedas de forma automatizada usando bots configurables, señales internas y trading manual.

Flujo recomendado para empezar:
1. Accede con tus credenciales.
2. Revisa el Dashboard, tu centro de control.
3. Configura una cuenta real en Exchanges o una cuenta de simulación en Paper.
4. Crea tu primer bot en Bots → Nuevo bot.
5. Usa Paper trading para validar la estratega antes de operar real.

Recomendación inicial: siempre empieza con paper trading. Valida tu estratega durante al menos una semana antes de usar dinero real.

## Dashboard

El Dashboard es el centro de control principal. Muestra:

- Equity total y P&L del día.
- Posiciones abiertas con P&L no realizado.
- Bots activos, pausados y deshabilitados.
- Alertas del optimizador y del sistema.
- Kill switch de emergencia (cierra todas las posiciones y pausa bots).

El Dashboard agrega datos de todas las cuentas y bots del usuario. No muestra datos de mercado en tiempo real ni análisis técnico avanzado.

## Bots

Un bot es un operador automatizado que escucha señales y ejecuta órdenes según tu configuración. Cada bot opera un único par (símbolo) en un timeframe específico.

### Lista de bots

La página Bots muestra todos tus bots con su estado, par, timeframe, modo de trading y P&L. Desde aquí puedes:
- Activar o pausar un bot.
- Editar configuración.
- Ver actividad reciente.
- Acceder al optimizer y effectiveness de cada bot.

### Crear un bot

Pasos para crear un bot:
1. Ve a Bots y pulsa "Nuevo bot".
2. Rellena el Básico: nombre, símbolo, timeframe, apalancamiento.
3. Configura Capital / SL: tipo de sizing (porcentaje o fijo USDT) y stop loss inicial.
4. Define Take Profits (opcional pero recomendado).
5. En la pestaña Activación, elige las fuentes de señal.

### Fuentes de activación

Cada bot puede tener una o varias fuentes activas simultáneamente:

- **Webhook externo**: TradingView u otro sistema envía alertas JSON al endpoint del bot. Ideal si ya tienes indicadores propios.
- **Señal interna — Indicador**: el sistema escanea usando el motor ICT o Quantum Gold interno. Dispara cuando detecta confluencia A/A+.
- **Scanner IA**: no disponible en fase 1.

### Estados del bot

- **Activo**: escucha y ejecuta señales.
- **Pausado**: no abre nuevas entradas, mantiene posiciones abiertas.
- **Deshabilitado**: no opera. Debes pausarlo antes de editar su configuración.

### Editar un bot

Permite modificar nombre, símbolo, timeframe, apalancamiento, capital, SL, TPs y fuentes de activación. Para editar debes pausar el bot primero.

### Actividad del bot

La página de actividad muestra:
- Señales recibidas y filtradas.
- Trades ejecutados.
- Rechazos y motivos.
- Logs de ejecución.

Úsala para depurar por qué un bot no opera aunque haya señales.

### Optimizer de bot

El optimizer de bot sugiere ajustes a los parámetros del bot basándose en su historial de trades. Puede recomendar:
- Stop loss según volatilidad del par.
- Take profits optimizados por win rate histórico.
- Apalancamiento recomendado.

### Effectiveness

Effectiveness muestra estadísticas de rendimiento del bot: win rate, profit factor, drawdown, número de trades y curva de equity.

## Posiciones

La página Posiciones muestra todas las posiciones abiertas y cerradas.

Para posiciones abiertas:
- Símbolo, dirección (LONG/SHORT), tamaño, precio de entrada, P&L no realizado.
- Stop loss y take profits activos.
- Bot o fuente que generó la posición.
- Botón para cerrar manualmente.

Si hay dos o más posiciones abiertas en el mismo símbolo, aparece un triángulo amarillo de alerta.

Posiciones cerradas muestran el historial con P&L realizado, duración y resultado.

## Analytics

Analytics muestra métricas agregadas de rendimiento de todos tus bots:

- P&L diario, semanal y mensual.
- Win rate por bot y por símbolo.
- Drawdown máximo.
- Ratio riesgo/beneficio promedio.
- Distribución de operaciones LONG vs SHORT.

Usa Analytics para comparar bots y decidir cuáles mantener activos.

## Exchanges

### Cuentas de exchange

La plataforma se conecta a exchanges de criptomonedas mediante API keys. Soporta Binance, BingX y Bitunix.

Pasos para añadir una cuenta real:
1. Ve a Exchanges en el menú lateral.
2. Pulsa "Añadir cuenta".
3. Selecciona el exchange.
4. Introduce un label descriptivo.
5. Introduce la API Key y API Secret.
6. Selecciona si la cuenta es de Futuros (USDⓈ-M).
7. Pulsa Guardar.

Seguridad:
- Crea API keys con permisos de solo lectura y trading.
- No actives retiros (withdrawal).
- Añade la IP del servidor en la configuración del exchange si es requerido.

Problemas comunes:
- "Invalid API key": verifica que no haya espacios al copiar/pegar.
- "IP restriction": añade la IP del servidor en el exchange.
- "No markets found": la cuenta debe tener saldo o haber operado al menos una vez.

### Historial de trades (Exchange Trades)

La página Historial / Exchange Trades muestra todas las operaciones ejecutadas en los exchanges conectados. Incluye:
- Símbolo, dirección, tamaño, precio de entrada y salida.
- Comisiones pagadas.
- P&L realizado.
- Bot o fuente asociada.
- Fecha y hora de ejecución.

Puedes filtrar por exchange, cuenta, símbolo, bot y rango de fechas.

## Manual Trading

La página Manual permite abrir operaciones manualmente.

Pasos:
1. Selecciona la cuenta (real o paper).
2. Selecciona el símbolo.
3. Elige dirección LONG o SHORT.
4. Introduce tamaño y apalancamiento.
5. Configura stop loss y take profits opcionales.
6. Confirma la orden.

Notas importantes:
- Las operaciones manuales siempre pueden abrir, incluso si hay conflictos con bots.
- El frontend muestra confirmación si hay conflictos.
- Ten cuidado con el capital disponible; los bots no conocen tus operaciones manuales.

## Paper Trading

Paper trading es una simulación. El bot opera como si fuera real, pero no envía dinero al exchange.

### Crear una cuenta paper

1. Ve a Paper en el menú lateral.
2. Pulsa "Crear cuenta paper".
3. Introduce un nombre y un balance inicial.
4. Selecciona el exchange de referencia (para precios y mercados).
5. Pulsa Crear.

### Asignar paper a un bot

Al crear o editar un bot, en Modo de trading selecciona Paper y elige la cuenta creada. El bot operará en simulación hasta que cambies a una cuenta real.

### Ventajas y limitaciones

Ventajas:
- Sin riesgo de pérdida real.
- Valida estrategias antes de poner dinero.
- Testea configuraciones de circuit breaker.
- Múltiples cuentas paper para diferentes estrategias.

Limitaciones:
- No simula slippage ni lag del exchange.
- No afecta el order book real.
- Precios de ejecución pueden diferir ligeramente.
- No garantiza resultados idénticos en real.

## Optimizer DB

El Optimizer DB analiza el histórico de tus bots y sugiere ajustes a los parámetros:

- Ajuste de stop loss según volatilidad del par.
- Take profits optimizados por win rate histórico.
- Apalancamiento recomendado.
- Auto-optimización: aplica cambios automáticamente tras N operaciones.

Recomendación: revisa el Optimizer DB al menos una vez por semana. Las sugerencias se basan en datos reales de tus operaciones.

## Docs

Docs es la página de documentación de la plataforma. En fase 1 muestra únicamente la guía de usuario de las páginas habilitadas.

Si no encuentras respuesta en Docs, contacta al administrador.

## Ajustes (Settings)

La página Ajustes permite configurar preferencias de usuario:

- Cambiar contraseña.
- Configurar notificaciones (Telegram, Discord, email).
- Preferencias de interfaz (tema, idioma si aplica).
- Datos de perfil.

No confundir con la administración del sistema, que no está disponible en fase 1.

## Gestión de riesgo

Stop loss automático: cada bot configura un SL inicial como porcentaje desde el precio de entrada. El sistema coloca la orden de stop loss en el exchange automáticamente.

Take profits: puedes configurar múltiples niveles. Ejemplo: TP1 +1.5% cierra 60%, TP2 +2.5% cierra el 40% restante.

Trailing stop: opcional. Activa un stop loss móvil que sigue el precio cuando alcanzas un beneficio determinado.

Breakeven: opcional. Cuando el precio alcanza un % de beneficio, el SL se mueve automáticamente al precio de entrada.

Circuit breaker global: si un bot acumula 3 stop losses consecutivos en cualquier modo, se pausa automáticamente. Se auto-resetea a las 24 horas.

Regla de oro: nunca arriesgues más del 2% de tu capital total por operación.

## Gestión de conflictos entre bots

El sistema gestiona automáticamente las interacciones entre posiciones abiertas en el mismo activo. Las reglas se aplican por fuente de señal.

Reglas principales:
- **Mismo sentido**: siempre se rechaza. Nunca se permiten dos posiciones LONG (o dos SHORT) en el mismo activo y cuenta.
- **Sentido contrario**: primero evalúa si la posición existente está en profit y la tendencia de 15 min le favorece. Si es así, rechaza automáticamente.
- **Manual**: las operaciones manuales siempre pueden abrir.

Configuración por fuente para sentido contrario:
- Cerrar anterior y abrir nueva (por defecto).
- Mantener ambas posiciones (hedge).
- Rechazar nueva señal.

Cada vez que un trade se rechaza por conflicto o una posición se cierra para dar paso a otra, recibirás notificación en Telegram/Discord si está configurado.

## FAQ — Fase 1

### ¿Por qué mi bot no opera aunque tengo señales en el backtest?
El backtest muestra todas las señales generadas. El bot solo opera las que cumplan sus filtros. Verifica: ¿el par está en la watchlist? ¿el tier/status está permitido en el bot? ¿el circuit breaker está abierto? ¿ya tiene el máximo de posiciones abiertas?

### ¿Puedo tener varios bots para el mismo par?
Sí. También puedes tener un solo bot con múltiples fuentes activas (Webhook + Indicador). Solo asegúrate de no superar el capital disponible si operan en la misma cuenta real.

### ¿Qué diferencia hay entre pausar y deshabilitar un bot?
Pausar: el bot deja de abrir nuevas posiciones pero mantiene las abiertas. Deshabilitar: el bot no opera en absoluto. Debes pausarlo antes de editar su configuración.

### ¿Cómo reseteo un circuit breaker?
Los circuit breakers se auto-resetean a las 24 horas. Si necesitas resetearlo manualmente, pausa el bot, edítalo (cualquier cambio mínimo) y guárdalo.

### ¿Puedo operar manualmente mientras tengo bots activos?
Sí, pero ten cuidado con el capital disponible. Los bots no saben de tus operaciones manuales y podrían abrir posiciones que superen tu margen.

### ¿El paper trading garantiza los mismos resultados en real?
No exactamente. Paper trading usa precios de mercado pero no simula slippage, lag ni liquidez real. Sirve para validar la lógica, no para prometer resultados idénticos.

### ¿Por qué no veo IA Engine, Scanner Live, Chart o Monte Carlo?
Esas funcionalidades no están habilitadas en esta fase. El asistente tampoco tiene documentación sobre ellas.

### ¿Quién puede usar el Optimizer DB?
En fase 1 el Optimizer DB está habilitado para los usuarios según la configuración de la plataforma. Si no tienes acceso, contacta al administrador.

### ¿El asistente puede ver mis posiciones?
No. Responde preguntas generales sobre el uso de la plataforma, pero no accede a posiciones, balances ni datos de mercado en tiempo real. No da recomendaciones de inversión.
