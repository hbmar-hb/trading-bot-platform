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
for sym in ['PENGU', 'XAUT']:
    resp = requests.get(f"http://localhost:8000/ai/symbol-real-stats/{sym}", headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if resp.status_code == 200:
        data = resp.json()
        print(f"\n{sym}: {len(data['open_positions'])} open positions")
        for p in data['open_positions']:
            print(f"  {p['side']} | entry=${p['entry_price']} | qty={p['quantity']} | unrealized_pnl={p['unrealized_pnl']:.4f}")
