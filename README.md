# Crypto Watch Agent

## My Question
Which of my three coins (BTC, ETH, SOL) is showing an unusual volatility spike or drawdown compared to its 30-day average?

## Watchlist
- BTC (Bitcoin)
- ETH (Ethereum)
- SOL (Solana)

## How to Run
1. Add the `GROQ_API_KEY`, `SHEET_ID`, and `GOOGLE_CREDENTIALS` to GitHub Secrets.
2. Go to the Actions tab and run the Daily Crypto Watch workflow.

## What the AI does vs. What my code does
* **The AI:** Looks at the data, searches the playbook, and recommends whether an alert is needed (in JSON format).
* **My Code:** Fetches the data, runs the tools, checks the AI's answer against strict guardrails, and writes the final approved decision to Google Sheets.

## Playbook Thresholds
* **Volatility:** High volatility signals unusual movement.
* **Trend:** Price far from the 30-day moving average means the trend is overextended.
* **Drawdown:** A drawdown >15% indicates a strong downward move.
* **Alert Rules:** Only alert if drawdown >15% OR price is >5% away from MA.
* **Wording Rules:** Never use buy, sell, long, short, or invest.

## Hand Check
I manually checked the BTC 30-day moving average against the Kraken API and verified the calculations match the Sheet output.

## Guardrails & Tests
* The AI cannot use buy/sell words (Blocked by guardrail).
* The AI must cite a valid playbook source (No valid source, no alert).
* All tests pass (6/6). I also intentionally broke the code to prove the red/green workflow works.

## Results & Conclusion
* Standard Agent: Passed all tests.
* Planner + Reviewer: Added validation but takes more API calls. 
* **Conclusion:** I chose the Standard Agent with Guardrails for the daily job because it is fast, accurate, and saves API limits.

*This project is for education only and is not financial advice.*
