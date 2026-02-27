"""
============================================
SMS NOTIFICATION SERVICE
Sends job summaries to tradies via Twilio
============================================
"""

import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from twilio.rest import Client

logger = logging.getLogger("tradie-ai")

_twilio_client = None


def get_twilio_client() -> Client:
    global _twilio_client
    if _twilio_client is None:
        _twilio_client = Client(
            os.getenv("TWILIO_ACCOUNT_SID"),
            os.getenv("TWILIO_AUTH_TOKEN"),
        )
    return _twilio_client


def send_job_lead_sms(tradie: dict, summary: dict) -> dict:
    """Send a job lead SMS to the tradie."""
    client = get_twilio_client()
    tz_name = tradie.get("businessHours", {}).get("timezone", "Australia/Melbourne")
    now = datetime.now(ZoneInfo(tz_name))

    urgency_emoji = {
        "emergency": "🚨 EMERGENCY",
        "soon": "⚡ URGENT-ISH",
        "normal": "📋 New Job Lead",
    }

    header = urgency_emoji.get(summary.get("urgency", "normal"), "📋 New Job Lead")

    lines = [
        header,
        "━━━━━━━━━━━━━━━",
        f"👤 {summary.get('caller_name', 'Unknown')}",
        f"📞 {summary.get('caller_phone', 'No number')}",
        f"📍 {summary.get('suburb', 'Not provided')}",
        "",
        f"🔧 {summary.get('job_description', 'No details')}",
        "",
        f"⏰ Timing: {summary.get('preferred_timing', 'Flexible')}",
    ]

    if summary.get("notes"):
        lines.append(f"📝 {summary['notes']}")

    lines += [
        "",
        f"Received: {now.strftime('%-I:%M %p, %a %-d %b')}",
        "",
        "Reply CALL to get their number sent back.",
    ]

    message_body = "\n".join(lines)

    try:
        result = client.messages.create(
            body=message_body,
            from_=os.getenv("TWILIO_SMS_FROM"),
            to=tradie["personalPhone"],
        )
        logger.info(f"SMS sent to {tradie['name']} — SID: {result.sid}")
        return {"success": True, "message_sid": result.sid}
    except Exception as e:
        logger.error(f"SMS failed for {tradie['name']}: {e}")
        return {"success": False, "error": str(e)}


def send_emergency_alert(tradie: dict, summary: dict) -> dict:
    """Send an emergency priority SMS to the tradie."""
    client = get_twilio_client()

    message_body = "\n".join([
        "🚨🚨 EMERGENCY CALL 🚨🚨",
        "",
        f"{summary.get('caller_name', 'Unknown')} — {summary.get('caller_phone', 'No number')}",
        f"📍 {summary.get('suburb', 'Unknown location')}",
        "",
        summary.get("job_description", "No details"),
        "",
        "CALL THEM ASAP",
    ])

    try:
        client.messages.create(
            body=message_body,
            from_=os.getenv("TWILIO_SMS_FROM"),
            to=tradie["personalPhone"],
        )
        logger.info(f"🚨 Emergency alert sent to {tradie['name']}")
        return {"success": True}
    except Exception as e:
        logger.error(f"Emergency alert failed for {tradie['name']}: {e}")
        return {"success": False, "error": str(e)}


def send_spam_blocked_sms(tradie: dict, spam_count: int) -> dict:
    """Send a daily spam summary."""
    client = get_twilio_client()
    message_body = (
        f"🛡️ Daily Spam Report\n"
        f"{spam_count} spam/sales calls blocked today. "
        f"Your AI receptionist handled them all. 👍"
    )

    try:
        client.messages.create(
            body=message_body,
            from_=os.getenv("TWILIO_SMS_FROM"),
            to=tradie["personalPhone"],
        )
        return {"success": True}
    except Exception as e:
        logger.error(f"Spam report SMS failed: {e}")
        return {"success": False}


def handle_incoming_sms(body: str) -> str | None:
    """Parse an incoming SMS command from the tradie."""
    commands = {
        "CALL": "send_last_caller_number",
        "BUSY": "set_status_busy",
        "BACK": "set_status_available",
        "OFF": "set_after_hours",
        "ON": "set_available",
    }
    return commands.get(body.strip().upper())
