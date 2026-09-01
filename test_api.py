import os
import urllib.parse

import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

API_KEY = os.getenv("ZENROWS_API_KEY")
if not API_KEY:
    raise SystemExit("ZENROWS_API_KEY not set. Add it to your .env file.")

payload = '{"0":{"json":{"skip":0,"take":20,"sort":"trending"}}}'
trpc_payload = urllib.parse.quote(payload)
url = f'https://flowgpt.com/api/trpc/prompt.getPrompts?batch=1&input={trpc_payload}'

params = {
    'url': url,
    'apikey': API_KEY,
    'antibot': 'true',
    'premium_proxy': 'true',  # FlowGPT returned RESP001 without this.
}

response = requests.get('https://api.zenrows.com/v1/', params=params, timeout=60)
with open('flowgpt_trpc_debug.json', 'w', encoding='utf-8') as f:
    f.write(response.text)

print(f"Saved to flowgpt_trpc_debug.json (HTTP {response.status_code})")
