# QueueStorm Investigator

QueueStorm Investigator is a lightweight support-copilot API for the SUST CSE Carnival 2026 preliminary challenge. It receives a customer complaint plus recent transaction history, identifies the most relevant transaction, checks whether the evidence supports the complaint, routes the case to the correct support department, and generates a safe agent/customer response.

Live submission shape:

- `GET /health`
- `POST /analyze-ticket`

## Tech Stack

- Python
- Django
- Django REST Framework
- Gunicorn for EC2 deployment
- Deterministic rule-based evidence engine
- SQLite is present only as the default Django database; the API itself is stateless

## Why Rule-Based Instead Of Hosted AI

The first version used a hosted Gemini AI integration with structured JSON output. We removed that dependency for the submitted version because the challenge heavily rewards reliability, schema correctness, safety, and response time.

The current rule-based analyzer is safer for this contest because:

- It does not require shipping or storing an AI API key.
- It does not depend on outbound model-provider network access during judging.
- It always returns exact enum values required by the problem statement.
- It avoids LLM hallucinations such as unauthorized refund promises or unsafe verification instructions.
- It responds quickly and predictably within the 30-second timeout.

External LLMs are allowed by the problem statement, but they are not required. The implementation keeps the core copilot behavior local and reproducible.

## API Contract

### `GET /health`

Returns service readiness:

```json
{"status":"ok"}
```

### `POST /analyze-ticket`

Accepts one ticket:

```json
{
  "ticket_id": "TKT-001",
  "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
  "language": "en",
  "channel": "in_app_chat",
  "user_type": "customer",
  "campaign_context": "boishakh_bonanza_day_1",
  "transaction_history": [
    {
      "transaction_id": "TXN-9101",
      "timestamp": "2026-04-14T14:08:22Z",
      "type": "transfer",
      "amount": 5000,
      "counterparty": "+8801719876543",
      "status": "completed"
    }
  ]
}
```

Returns the required structured response:

```json
{
  "ticket_id": "TKT-001",
  "relevant_transaction_id": "TXN-9101",
  "evidence_verdict": "consistent",
  "case_type": "wrong_transfer",
  "severity": "high",
  "department": "dispute_resolution",
  "agent_summary": "Ticket TKT-001 appears to be a wrong transfer case linked to TXN-9101 for 5000 BDT. Evidence verdict: consistent.",
  "recommended_next_action": "Send TXN-9101 to dispute resolution for recipient and transfer validation before any next step.",
  "customer_reply": "We have noted your concern about transaction TXN-9101. An authorized support agent will review it, and any eligible amount will be handled through official channels after verification.",
  "human_review_required": true,
  "confidence": 0.86,
  "reason_codes": ["wrong_transfer", "transaction_match", "amount_mentioned"]
}
```

HTTP behavior:

- `200`: successful analysis
- `400`: malformed input or missing required fields
- `422`: semantically invalid input, such as an empty complaint
- `500`: non-sensitive internal error message

## Technical Approach

The implementation is in `backend/ticket_analyzer/views.py`.

The analyzer performs four main steps:

1. **Classify the complaint**
   It detects categories such as `wrong_transfer`, `payment_failed`, `duplicate_payment`, `merchant_settlement_delay`, `agent_cash_in_issue`, `refund_request`, and `phishing_or_social_engineering` using English, Bangla, and Banglish keyword patterns.

2. **Find the relevant transaction**
   Each transaction is scored using:
   - amount mentioned in the complaint
   - counterparty/phone-number fragment match
   - expected transaction type for the detected case type
   - transaction status relevance

3. **Decide the evidence verdict**
   The API returns:
   - `consistent` when transaction data supports the complaint
   - `inconsistent` when transaction status contradicts the complaint
   - `insufficient_data` when there is no clear matching transaction or the case is safety-only

4. **Route and respond safely**
   The service assigns severity, department, `human_review_required`, confidence, reason codes, an agent summary, a recommended next action, and a safe customer reply.

## Safety Guardrails

The service is designed as an internal copilot, not an autonomous financial decision maker.

It never asks for:

- PIN
- OTP
- password
- full card number
- CVV

It also avoids saying that a refund, reversal, account recovery, or unblock is guaranteed. Instead, it uses cautious language such as:

```text
Any eligible amount will be handled through official channels after verification.
```

Human review is required for:

- wrong transfers
- duplicate payments
- phishing or social-engineering cases
- high or critical severity cases
- inconsistent evidence
- insufficient evidence

## MODELS

No external model is used in the submitted implementation.

- Model: none
- Runtime: local Python/Django rules
- Reason: reliable schema compliance, low latency, no API key exposure, no external AI dependency

Earlier prototype:

- A Gemini-based version was tested during development.
- It was replaced by the deterministic analyzer to reduce deployment and safety risk.

## Local Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend
python manage.py runserver 0.0.0.0:8000
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Analyze ticket:

```bash
curl -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
    "transaction_history": [
      {
        "transaction_id": "TXN-9101",
        "timestamp": "2026-04-14T14:08:22Z",
        "type": "transfer",
        "amount": 5000,
        "counterparty": "+8801719876543",
        "status": "completed"
      }
    ]
  }'
```

## EC2 Deployment

Install dependencies:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git tmux
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Run with Gunicorn:

```bash
cd backend
export DJANGO_SECRET_KEY='replace-with-any-long-random-string'
export DJANGO_DEBUG=false
export DJANGO_ALLOWED_HOSTS='YOUR_EC2_PUBLIC_IP,localhost,127.0.0.1'
gunicorn support_copilot.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 30
```

For hackathon uptime, run that command inside `tmux`:

```bash
tmux new -s questorm
```

Detach without stopping the API:

```text
Ctrl+B, then D
```

Reconnect:

```bash
tmux attach -t questorm
```

More detailed EC2 notes are in `EC2_RUNBOOK.md`.

## Environment Variables

See `.env.example`.

- `DJANGO_SECRET_KEY`: Django secret key, supplied by the server environment
- `DJANGO_DEBUG`: `true` locally, `false` on EC2
- `DJANGO_ALLOWED_HOSTS`: comma-separated host/IP allowlist

No AI API key is required for the submitted implementation.

## Tests

```bash
cd backend
python manage.py check
python manage.py test
```

The tests cover:

- `/health`
- successful wrong-transfer analysis
- inconsistent payment evidence
- phishing/social-engineering safety routing
- missing and empty required fields

## Deliverables

- `README.md`: setup, architecture, AI/model approach, safety logic, assumptions, limitations
- `requirements.txt`: Python dependencies
- `.env.example`: reproducible environment variable names
- `sample_output.json`: example input/output
- `EC2_RUNBOOK.md`: EC2 deployment steps

## Known Limitations

- Keyword detection is conservative and may miss unusual phrasing.
- Bangla/Banglish support is basic but present.
- The service does not connect to real ledger, payment, refund, or account systems.
- The service does not perform financial actions; it only classifies, routes, and recommends safe next steps.
