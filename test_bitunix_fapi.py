"""
Script de prueba para verificar credenciales de Bitunix Futures API (fapi.bitunix.com)
con la implementación corregida.

Uso:
    python test_bitunix_fapi.py <API_KEY> <SECRET>
"""
import hashlib
import json
import secrets
import sys
import time

import requests

BASE_URL = "https://fapi.bitunix.com"


def generate_nonce() -> str:
    """Genera nonce de 32 caracteres hexadecimales."""
    return secrets.token_hex(16)  # 16 bytes = 32 chars hex


def sign_request(api_key: str, secret: str, nonce: str, timestamp: str, query_params: str, body: str) -> str:
    """Firma según documentación oficial de Bitunix."""
    digest_input = nonce + timestamp + api_key + query_params + body
    digest = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
    sign_input = digest + secret
    return hashlib.sha256(sign_input.encode("utf-8")).hexdigest()


def test_credentials(api_key: str, secret: str):
    """Prueba las credenciales contra el endpoint de cuenta de futuros."""
    nonce = generate_nonce()
    timestamp = str(int(time.time() * 1000))

    # GET /api/v1/futures/account (sin params ni body)
    query_params = ""
    body = ""

    signature = sign_request(api_key, secret, nonce, timestamp, query_params, body)

    headers = {
        "api-key": api_key,
        "sign": signature,
        "timestamp": timestamp,
        "nonce": nonce,
        "Content-Type": "application/json",
    }

    url = f"{BASE_URL}/api/v1/futures/account"
    digest_input = nonce + timestamp + api_key + query_params + body

    print("=" * 60)
    print("TEST BITUNIX FUTURES API (fapi.bitunix.com)")
    print("=" * 60)
    print(f"URL: {url}")
    print(f"Nonce: {nonce} ({len(nonce)} chars)")
    print(f"Timestamp: {timestamp}")
    print(f"Headers: {json.dumps(headers, indent=2)}")
    print(f"Digest input: '{digest_input}'")
    print()

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"Status: {resp.status_code}")
        print(f"Response: {resp.text}")

        data = resp.json()
        if data.get("code") == 0:
            print("\n✅ CREDENCIALES VÁLIDAS — Conexión exitosa")
        elif data.get("code") == 10007:
            print("\n❌ ERROR 10007 — Signature Error (la firma no coincide)")
            print("   Esto indica un bug en la generación de la firma.")
        elif data.get("code") == 10003:
            print("\n❌ ERROR 10003 — API Key inválida o sin permisos")
        else:
            print(f"\n❌ ERROR {data.get('code')} — {data.get('msg')}")

    except Exception as e:
        print(f"\n❌ Error de conexión: {e}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(f"Uso: python {sys.argv[0]} <API_KEY> <SECRET>")
        sys.exit(1)

    test_credentials(sys.argv[1], sys.argv[2])
