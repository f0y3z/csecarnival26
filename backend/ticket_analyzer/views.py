import re
from decimal import Decimal, InvalidOperation
from typing import Any

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response


CASE_TYPES = {
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
}

DEPARTMENTS = {
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
}

def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in text for term in terms)


def _amounts_from_text(text: str) -> list[Decimal]:
    amounts = []
    for raw in re.findall(r"(?<!\d)(\d+(?:,\d{3})*(?:\.\d+)?)(?!\d)", text):
        try:
            value = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        if value >= 10:
            amounts.append(value)
    return amounts


def _normalize_counterparty(value: Any) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _classify_case(complaint: str, user_type: str, history: list[dict[str, Any]]) -> str:
    text = complaint.lower()

    if _contains_any(
        text,
        (
            "scam",
            "fraud",
            "phishing",
            "suspicious",
            "fake",
            "otp",
            "pin",
            "password",
            "verification code",
            "অটিপি",
            "পিন",
            "পাসওয়ার্ড",
            "পাসওয়ার্ড",
        ),
    ):
        return "phishing_or_social_engineering"

    if _contains_any(text, ("duplicate", "twice", "double charged", "charged two", "দুইবার", "ডাবল")):
        return "duplicate_payment"

    if _contains_any(text, ("settlement", "settle", "merchant payment", "merchant balance", "মার্চেন্ট")):
        return "merchant_settlement_delay"

    if _contains_any(text, ("cash in", "cash-in", "cashin", "agent deposit", "deposit through agent", "ক্যাশ ইন")):
        return "agent_cash_in_issue"

    if _contains_any(text, ("wrong number", "wrong recipient", "wrong account", "mistakenly sent", "ভুল নাম্বার", "ভুল নম্বর")):
        return "wrong_transfer"

    if _contains_any(text, ("failed", "deducted", "debited", "pending", "payment did not", "পেমেন্ট হয়নি", "কাটা")):
        return "payment_failed"

    if _contains_any(text, ("refund", "return my money", "money back", "রিফান্ড", "টাকা ফেরত")):
        if any(tx.get("type") == "payment" for tx in history):
            return "refund_request"
        return "refund_request"

    if user_type == "merchant":
        return "merchant_settlement_delay"
    if user_type == "agent":
        return "agent_cash_in_issue"
    return "other"


def _department_for(case_type: str) -> str:
    return {
        "wrong_transfer": "dispute_resolution",
        "payment_failed": "payments_ops",
        "refund_request": "customer_support",
        "duplicate_payment": "payments_ops",
        "merchant_settlement_delay": "merchant_operations",
        "agent_cash_in_issue": "agent_operations",
        "phishing_or_social_engineering": "fraud_risk",
        "other": "customer_support",
    }.get(case_type, "customer_support")


def _expected_tx_types(case_type: str) -> set[str]:
    return {
        "wrong_transfer": {"transfer"},
        "payment_failed": {"payment", "transfer", "cash_out"},
        "refund_request": {"payment", "transfer", "cash_out", "refund"},
        "duplicate_payment": {"payment"},
        "merchant_settlement_delay": {"settlement", "payment"},
        "agent_cash_in_issue": {"cash_in"},
    }.get(case_type, set())


def _score_transaction(tx: dict[str, Any], complaint: str, amounts: list[Decimal], case_type: str) -> int:
    score = 0
    tx_amount = tx.get("amount")
    try:
        amount = Decimal(str(tx_amount))
    except (InvalidOperation, TypeError):
        amount = None

    if amount is not None and amount in amounts:
        score += 5

    counterparty = _normalize_counterparty(tx.get("counterparty"))
    if counterparty and counterparty[-8:] in _normalize_counterparty(complaint):
        score += 4

    tx_type = str(tx.get("type", "")).lower()
    if tx_type in _expected_tx_types(case_type):
        score += 3

    status_value = str(tx.get("status", "")).lower()
    complaint_lower = complaint.lower()
    if status_value and status_value in complaint_lower:
        score += 2

    if case_type == "payment_failed" and status_value in {"failed", "pending"}:
        score += 3
    if case_type in {"wrong_transfer", "duplicate_payment", "refund_request"} and status_value == "completed":
        score += 2
    if case_type == "merchant_settlement_delay" and status_value in {"pending", "failed"}:
        score += 2

    return score


def _find_relevant_transaction(
    complaint: str, history: list[dict[str, Any]], case_type: str
) -> tuple[dict[str, Any] | None, str, list[str]]:
    if case_type == "phishing_or_social_engineering":
        return None, "insufficient_data", ["safety_only_case"]

    if not history:
        return None, "insufficient_data", ["no_transaction_history"]

    amounts = _amounts_from_text(complaint)
    scored = [(_score_transaction(tx, complaint, amounts, case_type), tx) for tx in history]
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_tx = scored[0]

    if best_score < 3:
        return None, "insufficient_data", ["no_clear_transaction_match"]

    reasons = ["transaction_match"]
    if amounts:
        reasons.append("amount_mentioned")

    verdict = "consistent"
    status_value = str(best_tx.get("status", "")).lower()

    if case_type == "payment_failed" and status_value == "completed":
        verdict = "inconsistent"
        reasons.append("status_contradicts_complaint")
    elif case_type == "wrong_transfer" and status_value in {"failed", "reversed"}:
        verdict = "inconsistent"
        reasons.append("status_contradicts_complaint")
    elif case_type == "merchant_settlement_delay" and status_value == "completed":
        verdict = "inconsistent"
        reasons.append("status_contradicts_complaint")
    elif case_type == "agent_cash_in_issue" and status_value == "completed":
        verdict = "inconsistent"
        reasons.append("status_contradicts_complaint")
    return best_tx, verdict, reasons


def _severity(case_type: str, tx: dict[str, Any] | None, verdict: str) -> str:
    if case_type == "phishing_or_social_engineering":
        return "critical"

    amount = Decimal("0")
    if tx is not None:
        try:
            amount = Decimal(str(tx.get("amount", 0)))
        except (InvalidOperation, TypeError):
            amount = Decimal("0")

    if verdict == "insufficient_data":
        return "medium"
    if amount >= 50000:
        return "critical"
    if case_type in {"wrong_transfer", "duplicate_payment"} or amount >= 5000:
        return "high"
    if case_type in {"payment_failed", "refund_request", "merchant_settlement_delay", "agent_cash_in_issue"}:
        return "medium"
    return "low"


def _human_review_required(case_type: str, severity: str, verdict: str) -> bool:
    return (
        case_type in {"wrong_transfer", "phishing_or_social_engineering", "duplicate_payment"}
        or severity in {"high", "critical"}
        or verdict != "consistent"
    )


def _safe_customer_reply(case_type: str, tx_id: str | None, verdict: str) -> str:
    tx_ref = f" transaction {tx_id}" if tx_id else " your reported issue"

    if case_type == "phishing_or_social_engineering":
        return (
            "We have flagged this as a possible security concern. Please use only official support "
            "channels and do not follow instructions from unknown callers or messages."
        )

    if verdict == "insufficient_data":
        return (
            "We have received your concern and need an agent to review the available details. "
            "Any eligible amount will be handled through official channels after verification."
        )

    if verdict == "inconsistent":
        return (
            f"We have reviewed the available record for{tx_ref}, but it does not fully match the concern "
            "described. A support agent will verify the details through official channels."
        )

    return (
        f"We have noted your concern about{tx_ref}. An authorized support agent will review it, "
        "and any eligible amount will be handled through official channels after verification."
    )


def _recommended_action(case_type: str, tx_id: str | None, verdict: str) -> str:
    tx_ref = tx_id or "the reported transaction"
    if case_type == "phishing_or_social_engineering":
        return "Escalate to fraud risk, preserve the complaint text, and advise response through official support only."
    if verdict == "insufficient_data":
        return "Ask the agent to collect non-sensitive identifying details and verify against official transaction records."
    if verdict == "inconsistent":
        return f"Review {tx_ref} manually because the available transaction status conflicts with the complaint."
    if case_type == "wrong_transfer":
        return f"Send {tx_ref} to dispute resolution for recipient and transfer validation before any next step."
    if case_type == "duplicate_payment":
        return f"Compare {tx_ref} with nearby payment records and escalate duplicate-charge evidence to payments ops."
    if case_type == "payment_failed":
        return f"Check ledger and provider status for {tx_ref}, then update the customer through official support."
    if case_type == "merchant_settlement_delay":
        return f"Check settlement batch and merchant ledger status for {tx_ref}."
    if case_type == "agent_cash_in_issue":
        return f"Verify agent cash-in record and customer balance posting for {tx_ref}."
    if case_type == "refund_request":
        return f"Review eligibility and transaction evidence for {tx_ref} before giving any refund decision."
    return "Route to customer support for triage and collect only non-sensitive context if needed."


def _sanitize_output_text(value: str) -> str:
    text = value
    unsafe_refund_patterns = (
        r"\bwe will refund\b",
        r"\bwill refund\b",
        r"\brefund will be processed\b",
        r"\bprocess a refund\b",
        r"\breverse the transaction\b",
        r"\bwill reverse\b",
        r"\baccount will be unblocked\b",
    )
    for pattern in unsafe_refund_patterns:
        text = re.sub(pattern, "any eligible amount will be handled through official channels", text, flags=re.I)
    return text


def _build_analysis(data: dict[str, Any]) -> dict[str, Any]:
    ticket_id = str(data["ticket_id"])
    complaint = str(data["complaint"])
    history = data.get("transaction_history") or []
    if not isinstance(history, list):
        history = []
    user_type = str(data.get("user_type") or "unknown").lower()

    case_type = _classify_case(complaint, user_type, history)
    tx, verdict, reason_codes = _find_relevant_transaction(complaint, history, case_type)
    relevant_tx_id = tx.get("transaction_id") if tx else None
    severity = _severity(case_type, tx, verdict)
    department = _department_for(case_type)
    human_review = _human_review_required(case_type, severity, verdict)

    amount_text = ""
    if tx and tx.get("amount") is not None:
        amount_text = f" for {tx.get('amount')} BDT"
    tx_text = f" linked to {relevant_tx_id}" if relevant_tx_id else " with no clear matching transaction"
    agent_summary = (
        f"Ticket {ticket_id} appears to be a {case_type.replace('_', ' ')} case{tx_text}{amount_text}. "
        f"Evidence verdict: {verdict}."
    )

    confidence = 0.86 if verdict == "consistent" else 0.68 if verdict == "inconsistent" else 0.45
    if case_type == "phishing_or_social_engineering":
        confidence = 0.9
    if case_type not in CASE_TYPES:
        case_type = "other"
    if department not in DEPARTMENTS:
        department = "customer_support"

    output = {
        "ticket_id": ticket_id,
        "relevant_transaction_id": relevant_tx_id,
        "evidence_verdict": verdict,
        "case_type": case_type,
        "severity": severity,
        "department": department,
        "agent_summary": agent_summary,
        "recommended_next_action": _recommended_action(case_type, relevant_tx_id, verdict),
        "customer_reply": _safe_customer_reply(case_type, relevant_tx_id, verdict),
        "human_review_required": human_review,
        "confidence": confidence,
        "reason_codes": [case_type, *reason_codes],
    }

    output["recommended_next_action"] = _sanitize_output_text(output["recommended_next_action"])
    output["customer_reply"] = _sanitize_output_text(output["customer_reply"])
    return output


@api_view(["GET"])
def health_check(request):
    return Response({"status": "ok"}, status=status.HTTP_200_OK)


@api_view(["POST"])
def analyze_ticket(request):
    data = request.data
    if not isinstance(data, dict):
        return Response({"error": "Request body must be a JSON object."}, status=status.HTTP_400_BAD_REQUEST)

    if "ticket_id" not in data:
        return Response({"error": "Missing required field: ticket_id."}, status=status.HTTP_400_BAD_REQUEST)
    if "complaint" not in data:
        return Response({"error": "Missing required field: complaint."}, status=status.HTTP_400_BAD_REQUEST)
    if str(data.get("complaint") or "").strip() == "":
        return Response({"error": "Complaint cannot be empty."}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    try:
        return Response(_build_analysis(data), status=status.HTTP_200_OK)
    except Exception:
        return Response({"error": "An internal error occurred during analysis."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
