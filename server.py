"""
============================================
TRADIE AI RECEPTIONIST — MAIN SERVER (Python)
Webhook handler for Vapi.ai voice agent
============================================
"""

import os
import json
import logging
import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from dotenv import load_dotenv

from prompts import build_system_prompt, build_first_message
from sms import (
    send_job_lead_sms,
    send_emergency_alert,
    send_spam_blocked_sms,
    handle_incoming_sms,
    get_twilio_client,
)

# ---- Setup ----
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("logs/calls.log"),
    ],
)
logger = logging.getLogger("tradie-ai")

# ---- Load tradie config ----
with open("tradies.json") as f:
    TRADIES_CONFIG = json.load(f)

# ---- In-memory stores (swap for Redis/DB in production) ----
call_logs: list[dict] = []
spam_counts: dict[str, int] = {}      # {tradie_id: count}
last_callers: dict[str, dict] = {}    # {tradie_id: {name, phone}}


# ===========================================
# HELPERS
# ===========================================

def find_tradie_by_phone_id(phone_number_id: str) -> dict | None:
    for t in TRADIES_CONFIG["tradies"]:
        if t["vapiPhoneNumberId"] == phone_number_id:
            return t
    return None


def find_tradie_by_personal_phone(phone: str) -> dict | None:
    normalized = phone.replace(" ", "")
    for t in TRADIES_CONFIG["tradies"]:
        if t["personalPhone"].replace(" ", "") == normalized:
            return t
    return None


# ===========================================
# DAILY SPAM REPORT BACKGROUND TASK
# ===========================================

async def daily_spam_report():
    """Send spam summary at 6pm Melbourne time every day."""
    while True:
        await asyncio.sleep(60)  # Check every minute
        now = datetime.now(ZoneInfo("Australia/Melbourne"))
        if now.hour == 18 and now.minute == 0:
            for tradie in TRADIES_CONFIG["tradies"]:
                count = spam_counts.get(tradie["id"], 0)
                if count > 0:
                    send_spam_blocked_sms(tradie, count)
                    spam_counts[tradie["id"]] = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks on startup."""
    task = asyncio.create_task(daily_spam_report())
    logger.info(f"🎙️  Tradie AI Receptionist running")
    logger.info(f"📞 Managing {len(TRADIES_CONFIG['tradies'])} tradies")
    yield
    task.cancel()


# ===========================================
# APP
# ===========================================

app = FastAPI(title="Tradie AI Receptionist", lifespan=lifespan)


# ===========================================
# VAPI WEBHOOK
# ===========================================

@app.post("/webhook/vapi")
async def vapi_webhook(request: Request):
    body = await request.json()
    message = body.get("message", {})

    if not message:
        return JSONResponse({})

    message_type = message.get("type", "")
    call = message.get("call", {})
    phone_number_id = call.get("phoneNumberId", "")

    logger.info(f"Vapi webhook: {message_type} | call: {call.get('id', 'n/a')}")

    # ---- Call starting: Vapi asks which assistant to use ----
    if message_type == "assistant-request":
        tradie = find_tradie_by_phone_id(phone_number_id)

        if not tradie:
            logger.warning(f"Unknown phone number ID: {phone_number_id}")
            return JSONResponse({})

        return JSONResponse({
            "assistant": {
                "model": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "temperature": 0.7,
                    "systemMessage": build_system_prompt(tradie),
                    "functions": [
                        {
                            "name": "end_call_report",
                            "description": "Submit the call summary report when the call is ending with a real customer",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "caller_name": {"type": "string", "description": "Customer name"},
                                    "caller_phone": {"type": "string", "description": "Customer phone number"},
                                    "suburb": {"type": "string", "description": "Customer suburb/location"},
                                    "job_description": {"type": "string", "description": "What job they need done — be specific"},
                                    "urgency": {"type": "string", "enum": ["normal", "soon", "emergency"], "description": "How urgent is the job"},
                                    "preferred_timing": {"type": "string", "description": "When the customer wants the work done"},
                                    "notes": {"type": "string", "description": "Any extra notes from the call"},
                                    "is_spam": {"type": "boolean", "description": "Whether the call was spam/sales"},
                                },
                                "required": ["caller_name", "caller_phone", "job_description", "urgency", "is_spam"],
                            },
                        }
                    ],
                },
                "voice": {
                    "provider": "eleven-labs",
                    "voiceId": "pFZP5JQG7iQjIQuC4Bku",  # REPLACE with your ElevenLabs Voice ID
                    # ALT: "TX3LPaxmHKxFdv7VOQHJ" — Liam (Aussie male)
                    "stability": 0.6,
                    "similarityBoost": 0.8,
                },
                "firstMessage": build_first_message(tradie),
                "endCallMessage": "No worries, have a good one!",
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-2",
                    "language": "en-AU",
                },
                "silenceTimeoutSeconds": 15,
                "maxDurationSeconds": 300,
                "endCallFunctionEnabled": True,
            }
        })

    # ---- AI called a function during the conversation ----
    elif message_type == "function-call":
        function_call = message.get("functionCall", {})

        if function_call.get("name") == "end_call_report":
            report = function_call.get("parameters", {})
            tradie = find_tradie_by_phone_id(phone_number_id)

            if not tradie:
                logger.error(f"Tradie not found for call report: {phone_number_id}")
                return JSONResponse({"result": "Report received"})

            # Log the call
            call_record = {
                "tradie_id": tradie["id"],
                "timestamp": datetime.utcnow().isoformat(),
                "call_id": call.get("id"),
                **report,
            }
            call_logs.append(call_record)

            if report.get("is_spam"):
                # ---- SPAM: just count it ----
                spam_counts[tradie["id"]] = spam_counts.get(tradie["id"], 0) + 1
                logger.info(
                    f"Spam blocked for {tradie['name']} "
                    f"(total today: {spam_counts[tradie['id']]})"
                )
            else:
                # ---- REAL CUSTOMER: send SMS ----
                last_callers[tradie["id"]] = {
                    "name": report.get("caller_name"),
                    "phone": report.get("caller_phone"),
                }

                if report.get("urgency") == "emergency":
                    send_emergency_alert(tradie, report)
                else:
                    send_job_lead_sms(tradie, report)

            return JSONResponse({"result": "Report processed and SMS sent"})

        return JSONResponse({"result": "OK"})

    # ---- Call ended ----
    elif message_type == "end-of-call-report":
        summary = message.get("summary", "")
        duration = call.get("duration")
        logger.info(f"Call completed — duration: {duration}s — summary: {summary[:200]}")

        # Store transcript
        transcript = message.get("transcript", "")
        existing = next((l for l in call_logs if l.get("call_id") == call.get("id")), None)
        if existing:
            existing["transcript"] = transcript
            existing["duration"] = duration
            existing["summary"] = summary

        return JSONResponse({})

    return JSONResponse({})


# ===========================================
# TWILIO SMS WEBHOOK — incoming texts from tradie
# ===========================================

@app.post("/webhook/sms-incoming")
async def sms_incoming(request: Request):
    form = await request.form()
    from_number = form.get("From", "")
    body = form.get("Body", "")

    tradie = find_tradie_by_personal_phone(from_number)

    if not tradie:
        logger.warning(f"SMS from unknown number: {from_number}")
        return Response(content="<Response></Response>", media_type="text/xml")

    command = handle_incoming_sms(body)

    if command == "send_last_caller_number":
        last = last_callers.get(tradie["id"])
        if last:
            client = get_twilio_client()
            client.messages.create(
                body=f"📞 Last caller: {last['name']}\n{last['phone']}",
                from_=os.getenv("TWILIO_SMS_FROM"),
                to=tradie["personalPhone"],
            )

    return Response(content="<Response></Response>", media_type="text/xml")


# ===========================================
# API ENDPOINTS — for dashboard / monitoring
# ===========================================

@app.get("/api/calls/{tradie_id}")
async def get_calls(tradie_id: str):
    tradie_calls = [c for c in call_logs if c.get("tradie_id") == tradie_id]
    real_calls = [c for c in tradie_calls if not c.get("is_spam")]
    spam_calls = [c for c in tradie_calls if c.get("is_spam")]

    return {
        "tradie_id": tradie_id,
        "total_calls": len(tradie_calls),
        "real_leads": len(real_calls),
        "spam_blocked": len(spam_calls),
        "calls": list(reversed(real_calls))[:50],
    }


@app.get("/api/spam-stats/{tradie_id}")
async def get_spam_stats(tradie_id: str):
    return {
        "tradie_id": tradie_id,
        "spam_blocked_today": spam_counts.get(tradie_id, 0),
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "tradies_loaded": len(TRADIES_CONFIG["tradies"]),
    }


# ===========================================
# RUN
# ===========================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 3000))
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=True)
