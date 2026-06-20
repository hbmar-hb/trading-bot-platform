# Indicadores internos de la plataforma

## Score de señal
El score es un número entre 0 y 100 que resume la fuerza de la señal. Se calcula a partir de:
- Confluencia ICT/SMC (Order Blocks, FVG, CHoCH, liquidez).
- Alineación de timeframe superior.
- Régimen de mercado detectado.
- Resultado del anti-fake.

## Quality Tier
Clasificación del score:
- **STRONG**: score >= 70.
- **MODERATE**: score entre 50 y 69.
- **WEAK**: score < 50.

## Success Probability
Probabilidad estimada de éxito de la señal, calibrada por el modelo anti-fake. Valores por encima de 0.5 son alcistas; por debajo, bajistas o de baja confianza.

## Regime (Régimen de mercado)
Clasificación del estado del mercado:
- **TRENDING_UP**: tendencia alcista clara.
- **TRENDING_DOWN**: tendencia bajista clara.
- **RANGING**: rango lateral, evitar entradas agresivas.
- **VOLATILE**: alta volatilidad, reducir tamaño.

## Anti-fake Status
- **REAL**: la señal parece legítima.
- **FAKE**: detecta características de falsa ruptura.
- **CAUTION**: requiere confirmación adicional.
- **BLOCK**: no se debe operar.

## PnL real vs paper
- **Real Performance**: operaciones ejecutadas con dinero real en el exchange.
- **Paper Performance**: operaciones simuladas sin riesgo.
