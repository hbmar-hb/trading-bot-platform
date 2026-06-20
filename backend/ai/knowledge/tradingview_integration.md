# Integración de TradingView con Quantum Trading

## Pasos para conectar un bot a TradingView

1. Ve a **Bots**, edita el bot que quieres conectar y activa la fuente **Webhook externo** en la pestaña Activación.
2. Asegúrate de que el bot esté en estado **active**.
3. Anota el `bot_id` (UUID del bot) y el `webhook_secret` del bot.
4. Configura la URL del webhook en la alerta de TradingView:
   ```
   POST https://app.getquantum.app/webhook
   ```
5. Usa este JSON en el mensaje de la alerta:
   ```json
   {
     "bot_id": "<uuid-del-bot>",
     "secret": "<webhook_secret-del-bot>",
     "action": "long",
     "price": "{{close}}"
   }
   ```
6. Las acciones permitidas son `long`/`buy`, `short`/`sell` y `close`/`flat`.
7. Para probar la conexión sin ejecutar un trade, envía `"test": true`.

## Activar webhook en el bot

1. Ve a **Bots** y edita el bot que quieres conectar.
2. En la pestaña **Activación**, marca la fuente **Webhook externo**.
3. Asegúrate de que el bot esté en estado **active** para que procese las señales.

## Datos necesarios de tu bot

Necesitas estos valores del bot:

- `bot_id`: el UUID del bot (aparece en la URL o en el detalle del bot).
- `webhook_secret`: el secreto del bot que se usa para autenticar las alertas.

## URL del endpoint

Usa el webhook global. El `bot_id` va dentro del cuerpo de la petición:

```
POST https://app.getquantum.app/webhook
```

También existe la ruta legacy por si prefieres incluir el `bot_id` directamente en la URL:

```
POST https://app.getquantum.app/webhook/{bot_id}
```

## Formato del JSON de alerta

El cuerpo de la alerta que envíes desde TradingView debe ser JSON y contener como mínimo:

```json
{
  "bot_id": "<uuid-del-bot>",
  "secret": "<webhook_secret-del-bot>",
  "action": "long"
}
```

Campos opcionales:

- `price`: precio de la señal, por ejemplo `"{{close}}"`.
- `indicator_values`: objeto con valores de indicadores.
- `test: true`: modo test; valida la conectividad sin ejecutar ningún trade.

## Ejemplo de mensaje de alerta en Pine Script

En TradingView, en la pestaña **Alertas**, usa este tipo de mensaje:

```json
{
  "bot_id": "123e4567-e89b-12d3-a456-426614174000",
  "secret": "mi-secreto-del-bot",
  "action": "long",
  "price": "{{close}}"
}
```

## Acciones permitidas

- `long` o `buy` para abrir posición larga.
- `short` o `sell` para abrir posición corta.
- `close` o `flat` para cerrar la posición.

## Probar la conexión

Envía una alerta con `"test": true`:

```json
{
  "bot_id": "<uuid-del-bot>",
  "secret": "<webhook_secret-del-bot>",
  "action": "long",
  "test": true
}
```

Si todo está bien, recibirás `test_accepted` y el mensaje:

> Webhook configurado correctamente. La señal de prueba llegó y pasó todas las validaciones.

## Notas importantes

- TradingView requiere que el endpoint responda en menos de 3 segundos.
- El procesamiento real del trade se encola en Celery, por lo que la respuesta es inmediata.
- En producción solo se aceptan peticiones desde las IPs oficiales de TradingView.
- El `secret` puede enviarse en texto plano.
