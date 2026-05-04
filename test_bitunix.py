import hashlib
import hmac
import json
import time
import requests

API_KEY = "e175bda3e3f81fef619b727fb588cce1"
SECRET = "fa4abc700aa1b912cdfc7c0d31f846eb"
TIMESTAMP = str(int(time.time() * 1000))
MESSAGE = TIMESTAMP + "GET" + "/api/v1/futures/account"
SIGNATURE = hmac.new(SECRET.encode(), MESSAGE.encode(), hashlib.sha256).hexdigest()

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "ACCESS-KEY": API_KEY,
    "ACCESS-SIGN": SIGNATURE,
    "ACCESS-TIMESTAMP": TIMESTAMP,
    "Content-Type": "application/json",
}

resp = requests.get("https://api.bitunix.com/api/v1/futures/account", headers=headers)
print(f"Status: {resp.status_code}")
print(f"Response: {resp.text[:500]}")