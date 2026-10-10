import hashlib
import hmac
import json
import os
import sys
import uuid

import httpx
from dotenv import load_dotenv

load_dotenv()
secret = os.environ["WHATSAPP_APP_SECRET"]
phone_id = os.environ["WHATSAPP_PHONE_NUMBER_ID"]
origin = os.getenv("APP_ORIGIN", "http://localhost:8000")

patient_phone, text = sys.argv[1], " ".join(sys.argv[2:])
payload = {
    "object": "whatsapp_business_account",
    "entry": [{"changes": [{"value": {
        "metadata": {"phone_number_id": phone_id},
        "messages": [{
            "id": f"wamid.TEST{uuid.uuid4().hex}",
            "from": patient_phone.lstrip("+"),
            "type": "text",
            "text": {"body": text},
        }],
    }}]}],
}
body = json.dumps(payload).encode()
signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
result = httpx.post(
    f"{origin}/webhooks/whatsapp", content=body,
    headers={"x-hub-signature-256": signature, "Content-Type": "application/json"},
)
print(result.status_code, result.text)
