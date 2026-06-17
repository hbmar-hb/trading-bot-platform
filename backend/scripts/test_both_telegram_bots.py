"""Envía un mensaje de prueba desde ambos bots de Telegram."""
from config.settings import settings
from app.services.notifier import send_telegram_sync


def main() -> None:
    if not settings.telegram_chat_id:
        print("❌ TELEGRAM_CHAT_ID no está configurado.")
        return

    print(f"🎯 Chat ID destino: {settings.telegram_chat_id}")

    # 1. TRADING BOT NOTIFIER (IA + trades reales)
    print("\n📤 Enviando test desde TRADING BOT NOTIFIER...")
    send_telegram_sync(
        "🧪 <b>Test TRADING BOT NOTIFIER</b>\n\n"
        "Si recibes este mensaje, las notificaciones de IA y trades reales "
        "se envían desde el bot correcto.",
    )
    print("✅ Mensaje de trading/IA enviado.")

    # 2. QUANTUM BOT NOTIFIER (bots solo alertas)
    if not settings.quantum_bot_token:
        print("\n⚠️ TELEGRAM_QUANTUM_BOT_TOKEN no está configurado.")
        return

    print("\n📤 Enviando test desde QUANTUM BOT NOTIFIER...")
    send_telegram_sync(
        "🧪 <b>Test QUANTUM BOT NOTIFIER</b>\n\n"
        "Si recibes este mensaje, las notificaciones de bots solo alertas "
        "se envían desde el bot correcto.",
        bot_token=settings.quantum_bot_token,
    )
    print("✅ Mensaje de solo alertas enviado.")


if __name__ == "__main__":
    main()
