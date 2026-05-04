#!/usr/bin/env python3
"""
Simula señales de TradingView para probar el webhook localmente.

Uso:
    python scripts/test_webhook.py --bot-id <uuid> --secret <secret> --action long
    python scripts/test_webhook.py --bot-id <uuid> --secret <secret> --action close --price 45000
"""
import argparse
import json
import sys

import httpx


def send_signal(
    bot_id: str,
    secret: str,
    action: str,
    price: float | None,
    base_url: str,
) -> None:
    payload: dict = {
        "secret": secret,
        "action": action,
    }
    if price is not None:
        payload["price"] = str(price)

    url = f"{base_url}/webhook/{bot_id}"
    print(f"\n→ POST {url}")
    print(f"  Body: {json.dumps(payload, indent=2)}")

    try:
        response = httpx.post(url, json=payload, timeout=10)
        print(f"\n← {response.status_code}")
        print(f"  {json.dumps(response.json(), indent=2)}")
    except httpx.ConnectError:
        print(f"\n❌ No se pudo conectar a {base_url}")
        print("   ¿Está el backend corriendo?")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Simula una señal de TradingView")
    parser.add_argument("--bot-id",  required=True, help="UUID del bot")
    parser.add_argument("--secret",  required=True, help="webhook_secret del bot")
    parser.add_argument("--action",  required=True, choices=["long", "short", "close"])
    parser.add_argument("--price",   type=float,    help="Precio de la señal (opcional)")
    parser.add_argument("--url",     default="http://localhost:8000", help="URL del backend")

    args = parser.parse_args()
    send_signal(args.bot_id, args.secret, args.action, args.price, args.url)


if __name__ == "__main__":
    main()
