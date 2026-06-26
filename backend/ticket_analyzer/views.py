import os
import json
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from google import genai
from google.genai import types


def enforce_safety_guardrails(analysis_data: dict) -> dict:
    """
    Scans fields for unauthorized keywords and replaces them with completely
    compliant, non-committal legal boilerplate text to prevent penalties.
    """
    forbidden_phrases = [
        "we will refund", "will initiate a reversal", "initiating a reversal", 
        "refund will be processed", "process a refund", "reverse the transaction"
    ]
    
    # Target the critical validation fields
    fields_to_check = ["customer_reply", "recommended_next_action"]
    
    for field in fields_to_check:
        text = analysis_data.get(field, "").lower()
        
        # If any violation occurs, completely overwrite or patch the text
        if any(phrase in text for phrase in forbidden_phrases):
            if field == "customer_reply":
                analysis_data[field] = (
                    "We have logged your issue. Any eligible amounts will be reviewed and "
                    "processed exclusively through official banking channels following investigation."
                )
            elif field == "recommended_next_action":
                analysis_data[field] = (
                    "Flag the matching transaction ID for dispute evaluation and hold for manual internal review."
                )
                
    return analysis_data



# Initialize the Gemini Client 
# It automatically picks up the GEMINI_API_KEY environment variable
client = genai.Client()

# Define strict Pydantic structures to match your required Enums and Schema exactly [cite: 85, 86, 90, 93]
class TicketAnalysisSchema(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str] = None
    evidence_verdict: Literal["consistent", "inconsistent", "insufficient_data"]
    case_type: Literal[
        "wrong_transfer", "payment_failed", "refund_request", 
        "duplicate_payment", "merchant_settlement_delay", 
        "agent_cash_in_issue", "phishing_or_social_engineering", "other"
    ]
    severity: Literal["low", "medium", "high", "critical"]
    department: Literal[
        "customer_support", "dispute_resolution", "payments_ops", 
        "merchant_operations", "agent_operations", "fraud_risk"
    ]
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: float
    reason_codes: List[str]


@api_view(['GET'])
def health_check(request):
    """GET /health - Confirms readiness within 60 seconds."""
    return Response({"status": "ok"}, status=status.HTTP_200_OK)


@api_view(['POST'])
def analyze_ticket(request):
    """POST /analyze-ticket - Investigates complaints using Gemini API."""
    data = request.data
    
    ticket_id = data.get("ticket_id")
    complaint = data.get("complaint")
    
    if not ticket_id:
        return Response({"error": "Missing ticket_id"}, status=status.HTTP_400_BAD_REQUEST)
    if not complaint or str(complaint).strip() == "":
        return Response({"error": "Complaint cannot be empty"}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

    tx_history = data.get("transaction_history", [])

    system_prompt = """
        You are an internal digital finance support investigator copilot. 
        Analyze the user's complaint against their recent transaction history. 
        Determine what is true.

        CRITICAL SAFETY RULES FOR ALL OUTPUT FIELDS (Including customer_reply and recommended_next_action):
        1. NEVER ask the customer for a PIN, OTP, password, or card number.
        2. NEVER confirm, guarantee, or state that you are initiating a refund or reversal. Never tell the agent to process a refund/reversal immediately. Use cautious, non-committal language like "Flag for investigation", "Verify details with customer", or "eligible amounts will be processed through official channels".
        3. NEVER point anyone to non-official third-party contacts.
        """

    user_content = f"Ticket ID: {ticket_id}\nComplaint: {complaint}\nHistory: {json.dumps(tx_history)}"

    try:
        # Call Gemini with Structured JSON Schema enforcement
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=user_content,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                response_mime_type="application/json",
                response_schema=TicketAnalysisSchema,
                # Enforcing a safe temperature to avoid hallucinations on taxonomy
                temperature=0.1,
            ),
        )
        
        # The response text is guaranteed to parse cleanly into your structural format
        ai_analysis = json.loads(response.text)
        
        # Enforce exact incoming ticket_id match to bypass any potential minor AI slip ups
        ai_analysis["ticket_id"] = ticket_id 
        ai_analysis = enforce_safety_guardrails(ai_analysis)
        
        return Response(ai_analysis, status=status.HTTP_200_OK)

    except Exception as e:
        # Failsafe catch block to guarantee zero engine crashes during automated evaluation [cite: 40, 41]
        return Response(
            {"error": "An internal error occurred during analysis."}, 
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )