from jose import jwt
import uuid
from datetime import datetime, timezone, timedelta
import requests

payload = {
    "sub": "f5a80663-7c05-494d-af46-6fd4bb17976a",
    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    "iat": datetime.now(timezone.utc),
    "type": "access",
    "iss": "trading-bot-api",
    "aud": "trading-bot-frontend",
    "jti": str(uuid.uuid4()),
}
token = jwt.encode(payload, "dc381283e6660d90579e2faf58f891bac97f65f78e5d29809cc1f6220a9f15d4", algorithm="HS256")
resp = requests.get("http://localhost:8000/ai/real-performance", headers={"Authorization": f"Bearer {token}"}, timeout=10)
data = resp.json()

print("Trades IA (detalle):")
for t in data['trades']:
    print(f"ID={t['id']} | {t['symbol']} | {t['side']} | entry={t.get('entry_price')} | exit={t['exit_price']} | qty={t['quantity']} | pnl={t['realized_pnl']} | fee={t['fee']}")
    
print("\n--- Verificar signos ---")
for t in data['trades']:
    entry = t.get('entry_price')
    exit_p = t.get('exit_price')
    qty = float(t['quantity'])
    side = t['side']
    pnl = float(t['realized_pnl'] or 0)
    if entry and exit_p and qty:
        if side == 'long':
            expected = (exit_p - entry) * qty
        else:
            expected = (entry - exit_p) * qty
        print(f"{t['symbol']} {side}: entry={entry:.4f} exit={exit_p:.4f} qty={qty:.2f} | expected={expected:.4f} | actual={pnl:.4f} | match={'✅' if abs(expected - pnl) < 0.001 else '❌ INVERTIDO' if abs(expected + pnl) < 0.001 else '❌'}")
