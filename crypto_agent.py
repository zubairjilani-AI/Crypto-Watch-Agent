import requests
import math
import os
import json
import sys

# ---------- 1. The Market Tool (From Assignment 1) ----------
URL = "https://api.kraken.com/0/public/OHLC"

def get_market_summary(coin):
    pairs = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD"}
    if coin not in pairs:
        return {"error": "Coin not allowed"}
        
    params = {"pair": pairs[coin], "interval": 1440}
    response = requests.get(URL, params=params)
    if response.status_code != 200:
        return {"error": "Kraken down"}
        
    data = response.json()
    if data.get("error"):
        return {"error": str(data["error"])}
        
    result_data = data.get("result", {})
    pair_key = [k for k in result_data.keys() if k != "last"][0]
    raw_candles = result_data[pair_key]
    
    completed = raw_candles[:-1]
    closes = [float(c[4]) for c in completed]
    last_30 = closes[-30:]
    
    cur_price = last_30[-1]
    ma_30 = sum(last_30) / len(last_30)
    
    mean_val = ma_30
    variance = sum((x - mean_val) ** 2 for x in last_30) / len(last_30)
    vol = math.sqrt(variance)
    
    peak = last_30[0]
    max_dd = 0
    for price in last_30:
        if price > peak: peak = price
        dd = (price - peak) / peak
        if dd < max_dd: max_dd = dd
            
    return {
        "coin": coin,
        "current_price": round(cur_price, 2),
        "ma_30": round(ma_30, 2),
        "volatility": round(vol, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "distance_from_ma_pct": round(((cur_price - ma_30) / ma_30) * 100, 2)
    }

# ---------- 2. The Playbook Tool ----------
def search_playbook(query):
    try:
        with open("playbook.md", "r") as f:
            text = f.read()
        return {"playbook": text} 
    except:
        return {"error": "playbook not found"}

# ---------- 3. The AI Agent ----------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"

def ask_ai(messages, tools=None):
    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
    payload = {"model": MODEL, "messages": messages, "temperature": 0.1}
    if tools: payload["tools"] = tools
    res = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    if res.status_code != 200: raise Exception(f"AI Error: {res.text}")
    return res.json()["choices"][0]["message"]

TOOLS = [
    {"type": "function", "function": {"name": "get_market_summary", "description": "Get Kraken data for BTC, ETH or SOL", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}}, "required": ["coin"]}}},
    {"type": "function", "function": {"name": "search_playbook", "description": "Search the rules", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
]

# ---------- 4. Guardrails (Step 7) ----------
BANNED_WORDS = ["buy", "sell", "long", "short", "invest", "trade"]
VALID_SOURCES = ["Volatility", "Trend", "Drawdown", "Alert Rules", "Wording Rules"]

def apply_guardrails(decision):
    try:
        d = json.loads(decision)
    except:
        return {"alert": False, "message": "Invalid JSON", "sources": []}
        
    # Check for advice words
    msg = d.get("message", "").lower()
    if any(word in msg for word in BANNED_WORDS):
        d["alert"] = False
        d["message"] = "Blocked by guardrail: Advice language detected."
        
    # Check sources
    valid_srcs = [s for s in d.get("sources", []) if s in VALID_SOURCES]
    if d.get("alert") and not valid_srcs:
        d["alert"] = False
        d["message"] = "Blocked by guardrail: No valid playbook source."
        
    # Fix the AI hyphen glitch
    d["message"] = d.get("message", "").replace("\u2011", "-").replace("\u2013", "-")
    
    d["sources"] = valid_srcs
    return d

# ---------- 5. Send to Google Sheet (With Safety Net) ----------
def send_to_sheet(decision):
    sheet_url = os.environ.get("SHEET_URL")
    if not sheet_url:
        print("No SHEET_URL found. Skipping sheet update.")
        return
    try:
        res = requests.post(sheet_url, json=decision, timeout=10)
        print(f"Sheet response: {res.status_code} - {res.text}")
    except Exception as e:
        # This safety net stops Google's error from breaking your code
        print(f"Note: Could not reach Google Sheet ({e}). The decision is printed above.")

# ---------- 6. The Agent Loop ----------
def run_agent():
    messages = [
        {"role": "system", "content": "You are a crypto watcher. Check BTC, ETH, SOL. Read the playbook. Reply in JSON: {'alert': true/false, 'message': 'short text', 'sources': ['Volatility']}"},
        {"role": "user", "content": "Check my coins and decide if an alert is needed."}
    ]
    
    for step in range(5):
        msg = ask_ai(messages, tools=TOOLS)
        if not msg.get("tool_calls"):
            print("RAW AI DECISION:", msg["content"])
            final = apply_guardrails(msg["content"])
            print("FINAL DECISION:", json.dumps(final, indent=2))
            send_to_sheet(final)
            return
        messages.append(msg)
        for tool in msg["tool_calls"]:
            name, args = tool["function"]["name"], json.loads(tool["function"]["arguments"])
            print(f"Tool: {name} -> {args}")
            res = get_market_summary(args.get("coin")) if name == "get_market_summary" else search_playbook(args.get("query"))
            messages.append({"role": "tool", "tool_call_id": tool["id"], "content": json.dumps(res)})
    print("Timeout")

if __name__ == "__main__":
    run_agent()
