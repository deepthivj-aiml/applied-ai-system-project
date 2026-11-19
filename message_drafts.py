"""Short private-message drafts with an optional OpenAI Responses API call."""
import json
import os
from urllib.request import Request, urlopen

from vlm_matcher import BASE_DIR, DEFAULT_MODEL, _load_local_env, _extract_output_text


def generate_message_draft(
    intent, source_report=None, target_report=None, has_attachment=False, reply_context=None,
):
    """Return an editable draft; report data is limited to public dog/report details."""
    _load_local_env()
    source_report = source_report or {}
    target_report = target_report or {}
    source_id = source_report.get("case_id", "your report")
    target_id = target_report.get("case_id", "the other report")
    if intent in {"Thank you / reunited", "thank_you"}:
        intent = "thank_you"
        fallback = (
            f"Hello, I wanted to thank you for helping with report {target_id}. "
            "Our dog is back home, and I really appreciate your kindness."
        )
        instruction = "Write a warm, concise thank-you from a dog owner whose dog has been reunited."
    elif intent == "reply":
        fallback = "Thanks for reaching out. I will compare the dog's markings and get back to you."
        instruction = (
            "Write a helpful, concise reply to the latest message in a private lost/found dog chat. "
            "Respond to the conversation without claiming a match is confirmed."
        )
    else:
        intent = "possible_match"
        fallback = (
            f"Hello, your report {target_id} may match my report {source_id}. "
            "Could you compare the dog's distinctive markings and let me know if they look the same?"
        )
        instruction = "Write a polite, concise message asking someone to compare a possible lost/found dog match."

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {"text": fallback, "generated": False}

    safe_details = {
        "intent": intent,
        "source_report": _public_report_details(source_report),
        "target_report": _public_report_details(target_report),
        "optional_attachment_selected": bool(has_attachment),
        "recent_chat_messages": [str(item)[:500] for item in (reply_context or [])[-4:]],
    }
    body = {
        "model": os.getenv("OPENAI_VLM_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "input": [{
            "role": "user",
            "content": (
                f"{instruction} Return only the message body, 2 to 4 short sentences. "
                "Do not invent a reward, promise, contact detail, or fact. "
                "Mention an attached gift only when the optional attachment is selected. "
                "Report details follow as JSON; do not include private contact information.\n"
                + json.dumps(safe_details, ensure_ascii=False)
            ),
        }],
        "max_output_tokens": 180,
        "reasoning": {"effort": "low"},
        "store": False,
    }
    request = Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            response_data = json.loads(response.read().decode("utf-8"))
        text = _extract_output_text(response_data).strip()
        if text:
            return {"text": text[:2000], "generated": True}
    except Exception:
        pass
    return {"text": fallback, "generated": False}


def _public_report_details(report):
    """Exclude private emails, local paths, and all fields outside dog report details."""
    return {
        "case_id": report.get("case_id"),
        "status": report.get("status"),
        "breed": report.get("breed"),
        "colour": report.get("colour"),
        "size": report.get("size"),
        "markings": report.get("markings"),
        "location": report.get("place_label"),
    }
