# QueueStorm Investigator

Dev-phase implementation for the SUST CSE Carnival 2026 Codex Community Hackathon preliminary problem.

The service exposes:

- `GET /health`
- `POST /analyze-ticket`

## Tech Stack

- Python
- Django
- Django REST Framework
- Deterministic rule-based evidence investigator

## Run Locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend
python manage.py runserver 0.0.0.0:8000
```

For an EC2 hackathon deployment without Docker, use Gunicorn:

```bash
cd backend
DJANGO_SECRET_KEY='replace-with-any-long-random-string' \
DJANGO_DEBUG=false \
DJANGO_ALLOWED_HOSTS='YOUR_EC2_PUBLIC_IP,localhost,127.0.0.1' \
../.venv/bin/gunicorn support_copilot.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 30
```

See [EC2_RUNBOOK.md](EC2_RUNBOOK.md) for the full deployment checklist and `systemd` option.

Health check:

```bash
curl http://127.0.0.1:8000/health
```

Analyze a ticket:

```bash
curl -X POST http://127.0.0.1:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today.",
    "language": "en",
    "channel": "in_app_chat",
    "user_type": "customer",
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

## API Behavior

`POST /analyze-ticket` returns the required schema:

- `ticket_id`
- `relevant_transaction_id`
- `evidence_verdict`
- `case_type`
- `severity`
- `department`
- `agent_summary`
- `recommended_next_action`
- `customer_reply`
- `human_review_required`
- `confidence`
- `reason_codes`

Malformed requests return `400`. Empty complaints return `422`. Internal errors return a non-sensitive `500` message.

## AI Approach

This dev-phase version uses a local rule-based investigator instead of a hosted LLM. That keeps latency low, avoids API key dependency, and works in restricted judge environments.

The analyzer:

- Detects complaint category from English, Bangla, and Banglish keywords.
- Scores transactions by mentioned amount, counterparty fragments, transaction type, and status.
- Produces `consistent`, `inconsistent`, or `insufficient_data` based on complaint evidence versus transaction history.
- Routes cases to the required departments using the problem taxonomy.

## MODELS

No external model is used in the current implementation.

- Model: none
- Runtime: local Python rules inside the Django API
- Reason: fast, reproducible, no network or secret dependency, enough for the required schema and safety guardrails

Future deployment can add an optional LLM reviewer behind the same schema, but the local path should remain as a fallback.

## Safety Logic

The service never asks customers for sensitive credentials in `customer_reply`. It also avoids confirming refunds, reversals, account recovery, or unblocks without authority.

Safety-sensitive or ambiguous cases are escalated with `human_review_required: true`, especially:

- suspicious social engineering complaints
- wrong transfers
- duplicate payments
- high or critical severity cases
- inconsistent or insufficient evidence

## Assumptions

- Transaction histories are short, as described in the problem statement.
- Exact enum values from the problem statement are mandatory.
- This repository is currently in development phase; production deployment settings will be finalized later.

## Known Limitations

- Keyword detection is intentionally conservative and may miss unusual phrasing.
- Bangla/Banglish coverage is basic.
- It does not call bank, ledger, or payment provider systems.
- It does not perform real refunds, reversals, or account actions.

## Tests

```bash
cd backend
../.venv/bin/python manage.py test
```

If using the existing local backend virtual environment:

```bash
cd backend
venv/bin/python manage.py test
```

## Environment

Copy `.env.example` values into your deployment environment:

- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`

Do not commit real secrets.
