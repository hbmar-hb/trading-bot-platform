"""
Test de firma Bitunix - Comparación con código PHP de referencia.
"""
import hashlib
import json
import secrets
import time

# Valores de prueba (mismos que usaría el código PHP)
API_KEY = "e175bda3e3f81fef619b727fb8be62f6"  # Tu API Key
SECRET = "TU_SECRET_AQUI"  # Necesito tu Secret para probar

def sign_php_style(nonce: str, timestamp: str, params: dict, body: str) -> str:
    """
    Implementación exacta según código PHP:
    
    PHP:
    $queryParamsString = '';
    ksort($params);
    foreach ($params as $key => $value) {
        $queryParamsString .= $key . $value;
    }
    $body = json_encode($params);
    $timestamp = (int)(microtime(true)*1000);
    $digest = hash('sha256' , $nonce.$timestamp.$apiKey.$queryParamsString.$body);
    $sign = hash('sha256', $digest.$secretKey);
    """
    # Crear queryParamsString ordenando params
    query_params = ""
    for key in sorted(params.keys()):
        query_params += str(key) + str(params[key])
    
    # Primer hash
    digest_input = nonce + timestamp + API_KEY + query_params + body
    print(f"Digest input: {digest_input[:100]}...")
    
    digest = hashlib.sha256(digest_input.encode()).hexdigest()
    print(f"Digest: {digest}")
    
    # Segundo hash
    sign_input = digest + SECRET
    print(f"Sign input: {sign_input[:80]}...")
    
    signature = hashlib.sha256(sign_input.encode()).hexdigest()
    print(f"Signature: {signature}")
    
    return signature

def test_get_account():
    """Test endpoint GET api/v1/futures/account (sin params)"""
    print("=" * 60)
    print("TEST: GET api/v1/futures/account")
    print("=" * 60)
    
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time() * 1000))
    params = {}  # Sin parámetros
    body = ""   # Sin body
    
    print(f"Nonce: {nonce}")
    print(f"Timestamp: {timestamp}")
    print(f"API Key: {API_KEY[:20]}...")
    print(f"Params: {params}")
    print(f"Body: '{body}'")
    
    sign = sign_php_style(nonce, timestamp, params, body)
    
    print(f"\nHeaders para enviar:")
    print(f"  api-key: {API_KEY}")
    print(f"  sign: {sign}")
    print(f"  timestamp: {timestamp}")
    print(f"  nonce: {nonce}")
    
    return {
        "api-key": API_KEY,
        "sign": sign,
        "timestamp": timestamp,
        "nonce": nonce,
    }

def test_post_margin_mode():
    """Test endpoint POST change_margin_mode (con params/body)"""
    print("\n" + "=" * 60)
    print("TEST: POST api/v1/futures/account/change_margin_mode")
    print("=" * 60)
    
    nonce = secrets.token_hex(16)
    timestamp = str(int(time.time() * 1000))
    params = {
        "symbol": "BTCUSDT",
        "marginMode": "ISOLATED",
        "marginCoin": "USDT",
    }
    body = json.dumps(params, separators=(",", ":"))
    
    print(f"Nonce: {nonce}")
    print(f"Timestamp: {timestamp}")
    print(f"API Key: {API_KEY[:20]}...")
    print(f"Params (sorted): {dict(sorted(params.items()))}")
    print(f"Body: {body}")
    
    # Para POST, en el código PHP los params son los mismos que el body
    # pero queryParamsString se construye de params ordenados
    sign = sign_php_style(nonce, timestamp, params, body)
    
    print(f"\nHeaders para enviar:")
    print(f"  api-key: {API_KEY}")
    print(f"  sign: {sign}")
    print(f"  timestamp: {timestamp}")
    print(f"  nonce: {nonce}")
    print(f"  Content-Type: application/json")
    
    return {
        "api-key": API_KEY,
        "sign": sign,
        "timestamp": timestamp,
        "nonce": nonce,
        "Content-Type": "application/json",
    }

if __name__ == "__main__":
    print("TEST DE FIRMA BITUNIX")
    print("Formato exacto del código PHP de referencia")
    print()
    
    if SECRET == "TU_SECRET_AQUI":
        print("ERROR: Edita el archivo y pon tu SECRET real")
        exit(1)
    
    # Test 1: GET sin params
    headers1 = test_get_account()
    
    # Test 2: POST con params
    headers2 = test_post_margin_mode()
    
    print("\n" + "=" * 60)
    print("COMPARACIÓN CON BACKEND")
    print("=" * 60)
    print("Revisa que los headers generados coincidan con los logs del backend")
    print("Si la firma es diferente, hay un error en la implementación.")
