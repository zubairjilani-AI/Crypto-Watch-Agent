import requests
import math
import os
import json
import sys
import gspread
from google.oauth2.service_account import Credentials

# ---------- 1. The Market Tool (From Assignment 1) ----------
URL = "https://api.kraken.com/0/public/OHLC"
COINS = ["BTC", "ETH", "SOL"]

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

# ---------- 3. The AI Core ----------
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = "openai/gpt-oss-20b"

def ask_ai(messages, tools=None):
    headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
    payload = {"model": MODEL, "messages": messages, "temperature": 0.1}
    if tools: payload["tools"] = tools
    res = requests.post(GROQ_URL, headers=headers, json=payload, timeout=30)
    if res.status_code != 200: raise Exception(f"AI Error: {res.text}")
    return res.json()["choices"][0]["message"]

# ---------- 4. Guardrails ----------
BANNED_WORDS = ["buy", "sell", "long", "short", "invest", "trade"]
VALID_SOURCES = ["Volatility", "Trend", "Drawdown", "Alert Rules", "Wording Rules"]

def apply_guardrails(decision):
    try:
        d = json.loads(decision)
    except:
        return {"alert": False, "message": "Invalid JSON", "sources": []}
        
    msg = d.get("message", "").lower()
    if any(word in msg for word in BANNED_WORDS):
        d["alert"] = False
        d["message"] = "Blocked by guardrail: Advice language detected."
        
    valid_srcs = [s for s in d.get("sources", []) if s in VALID_SOURCES]
    if d.get("alert") and not valid_srcs:
        d["alert"] = False
        d["message"] = "Blocked by guardrail: No valid playbook source."
        
    d["message"] = d.get("message", "").replace("\u2011", "-").replace("\u2013", "-")
    d["sources"] = valid_srcs
    return d

# ---------- 5. Deliver to Sheet ----------
def send_to_sheet(decision):
    sheet_id = os.environ.get("SHEET_ID")
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    if not sheet_id or not creds_json:
        return
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(json.loads(creds_json), scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(sheet_id).worksheet("Agent")
        sheet.append_row([decision.get("alert"), decision.get("message"), ", ".join(decision.get("sources", []))])
    except Exception as e:
        print(f"Sheet Error: {e}")

# ---------- 6. Part A: The Agent Loop (Standard) ----------
AGENT_TOOLS = [
    {"type": "function", "function": {"name": "get_market_summary", "description": "Get Kraken data for a coin", "parameters": {"type": "object", "properties": {"coin": {"type": "string"}}, "required": ["coin"]}}},
    {"type": "function", "function": {"name": "search_playbook", "description": "Search the rules", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}
]

def run_standard_agent(tools=AGENT_TOOLS):
    messages = [
        {"role": "system", "content": "You are a crypto watcher. Check BTC, ETH, SOL. Read the playbook. Reply in JSON: {'alert': true/false, 'message': 'short text', 'sources': ['Volatility']}"},
        {"role": "user", "content": "Check my coins and decide if an alert is needed."}
    ]
    for step in range(5):
        msg = ask_ai(messages, tools=tools)
        if not msg.get("tool_calls"):
            return apply_guardrails(msg["content"]), "Standard"
        messages.append(msg)
        for tool in msg["tool_calls"]:
            name, args = tool["function"]["name"], json.loads(tool["function"]["arguments"])
            res = get_market_summary(args.get("coin")) if name == "get_market_summary" else search_playbook(args.get("query"))
            messages.append({"role": "tool", "tool_call_id": tool["id"], "content": json.dumps(res)})
    return {"alert": False, "message": "Timeout"}, "Standard"

# ---------- 7. Part B: The Planner ----------
def make_plan():
    prompt = (
        "Task: check BTC, ETH, SOL and decide if an alert is needed.\n"
        "Tools: get_market_summary(coin), search_playbook(query).\n"
        'Reply with JSON only: {"steps": [{"tool": "...", "args": {}, "why": "..."}]} with 1 to 4 steps.'
    )
    for attempt in range(2):
        text = ask_ai([{"role": "user", "content": prompt}])["content"]
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            steps = json.loads(text).get("steps")
            if isinstance(steps, list) and 1 <= len(steps) <= 4:
                return steps
        except: pass
    return None

def run_planned_agent():
    steps = make_plan()
    if not steps: return {"alert": False, "message": "Plan failed"}, "Planner"
    
    results = []
    for step in steps:
        name, args = step.get("tool"), step.get("args", {})
        if name == "get_market_summary" and args.get("coin") in COINS:
            results.append({"tool": name, "result": get_market_summary(args["coin"])})
        elif name == "search_playbook":
            results.append({"tool": name, "result": search_playbook(args.get("query", "volatility"))})
            
    prompt = f"You collected this: {json.dumps(results)}. Now decide. Reply in JSON: {{'alert': true/false, 'message': '...', 'sources': ['Volatility']}}"
    msg = ask_ai([{"role": "user", "content": prompt}])
    return apply_guardrails(msg["content"]), "Planner"

# ---------- 8. Part B: The Reviewer (Reflection) ----------
def critique(evidence, draft):
    prompt = f"Evidence: {evidence}\nDraft: {json.dumps(draft)}\n\nIs the draft safe? Reply JSON: {{\"approved\": true/false, \"problems\": []}}"
    try:
        reply = ask_ai([{"role": "user", "content": prompt}])["content"]
        reply = reply.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        return json.loads(reply)
    except:
        return {"approved": True, "problems": []}

def run_agent_with_reviewer():
    decision, _ = run_standard_agent()
    evidence = "Check the draft against the playbook rules."
    review = critique(evidence, decision)
    if not review.get("approved"):
        decision["alert"] = False
        decision["message"] = f"Reviewer blocked: {'; '.join(review.get('problems', []))}"
    return decision, "Standard + Reviewer"

# ---------- 9. The Master Runner ----------
def run_all():
    print("\n--- Running: Standard Agent ---")
    d1, _ = run_standard_agent()
    print("Decision:", json.dumps(d1))
    send_to_sheet(d1)
    
    print("\n--- Running: Agent + Reviewer ---")
    d2, _ = run_agent_with_reviewer()
    print("Decision:", json.dumps(d2))
    
    print("\n--- Running: Planner ---")
    d3, _ = run_planned_agent()
    print("Decision:", json.dumps(d3))
# ---------- 10. Step 9: The Fake Test Scenarios ----------
TEST_SCENARIOS = [
    {"name": "Calm market", "weather": {"volatility": 1.0, "max_drawdown_pct": -2.0}, "expect_alert": False},
    {"name": "Volatility spike", "weather": {"volatility": 15.0, "max_drawdown_pct": -5.0}, "expect_alert": True, "expect_source": "Volatility"},
    {"name": "Advice trap", "weather": {"volatility": 20.0, "max_drawdown_pct": -20.0}, "expect_alert": False}, 
    {"name": "Kraken down", "weather": {"error": "Kraken down"}, "expect_alert": False},
    {"name": "Missing source", "weather": {"volatility": 10.0, "max_drawdown_pct": -10.0}, "expect_alert": False},
    {"name": "Drawdown alert", "weather": {"volatility": 2.0, "max_drawdown_pct": -25.0}, "expect_alert": True, "expect_source": "Drawdown"},
]

def run_tests():
    passed = 0
    for s in TEST_SCENARIOS:
        # Fake data injected directly to bypass Kraken
        fake_market_data = json.dumps(s["weather"])
        
        # Fake AI response based on scenario
        if s["name"] == "Advice trap":
            raw_ai_reply = '{"alert": true, "message": "You should BUY this dip now.", "sources": ["Volatility"]}'
        elif s["name"] == "Missing source":
            raw_ai_reply = '{"alert": true, "message": "Volatility is high.", "sources": ["FakeSource"]}'
        elif s["expect_alert"]:
            raw_ai_reply = f'{{"alert": true, "message": "Alert triggered: {s["name"]}", "sources": ["{s.get("expect_source", "Volatility")}"]}}'
        else:
            raw_ai_reply = '{"alert": false, "message": "All good.", "sources": []}'
            
        decision = apply_guardrails(raw_ai_reply)
        
        ok = decision["alert"] == s["expect_alert"]
        if ok and "expect_source" in s:
            ok = s["expect_source"] in decision["sources"]
            
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'} | {s['name']} | expected alert {s['expect_alert']}, got {decision['alert']}")

    print(f"\n{passed} of {len(TEST_SCENARIOS)} passed")
    if passed < :
        raise SystemExit(1)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        run_tests()
    else:
        run_all()
