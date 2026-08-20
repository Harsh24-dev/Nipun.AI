"""
Safe-response handlers.

For each non-normal safety tag, build a supportive / official-resource ResponseCard
INSTEAD of the normal RAG answer. These deliberately do not diagnose, advise, or
provide any harmful content — they acknowledge, express support where appropriate,
and point to the relevant official channel.

Messages are provided in English and Hindi (the vulnerable-audience defaults); other
languages fall back to English until full localisation lands.
"""

from __future__ import annotations

import structlog

from src.core.metrics import SAFETY_GATE_TOTAL
from src.safety.resources import crisis_resources

log = structlog.get_logger("safety.handlers")

# tag -> {lang -> (title, summary)}. "en" is the required fallback.
_MESSAGES: dict[str, dict[str, tuple[str, str]]] = {
    "self_harm": {
        "en": (
            "You are not alone",
            "I'm really sorry you're feeling this way, and I'm glad you reached out. "
            "I can't provide crisis counselling, but please talk to someone who can help "
            "right now — a trusted person near you, or a mental-health professional. "
            "Please contact an official mental-health helpline or your nearest government hospital.",
        ),
        "hi": (
            "आप अकेले नहीं हैं",
            "आप ऐसा महसूस कर रहे हैं, इसके लिए मुझे बहुत खेद है, और अच्छा हुआ कि आपने बात की। "
            "मैं संकट-परामर्श नहीं दे सकता, लेकिन कृपया अभी किसी भरोसेमंद व्यक्ति या मानसिक "
            "स्वास्थ्य विशेषज्ञ से बात करें। कृपया किसी आधिकारिक मानसिक-स्वास्थ्य हेल्पलाइन या "
            "अपने नज़दीकी सरकारी अस्पताल से संपर्क करें।",
        ),
    },
    "medical_emergency": {
        "en": (
            "This may be a medical emergency",
            "This sounds urgent. Please contact local emergency services or go to the "
            "nearest hospital immediately. I can't give medical treatment advice — getting "
            "a medical professional involved right now is the safest thing to do.",
        ),
        "hi": (
            "यह एक चिकित्सा आपात स्थिति हो सकती है",
            "यह गंभीर लगता है। कृपया तुरंत स्थानीय आपातकालीन सेवाओं से संपर्क करें या नज़दीकी "
            "अस्पताल जाएँ। मैं इलाज की सलाह नहीं दे सकता — अभी किसी चिकित्सक की मदद लेना सबसे सुरक्षित है।",
        ),
    },
    "child_safety": {
        "en": (
            "Please report this to the authorities",
            "This is a serious matter involving a child's safety. Please report it to the "
            "official child-protection authorities and the police. I can't assist with this "
            "topic beyond pointing you to official help.",
        ),
        "hi": (
            "कृपया इसकी सूचना अधिकारियों को दें",
            "यह किसी बच्चे की सुरक्षा से जुड़ा गंभीर मामला है। कृपया इसकी सूचना आधिकारिक बाल-संरक्षण "
            "अधिकारियों और पुलिस को दें। मैं इस विषय पर आधिकारिक मदद की ओर इशारा करने के अलावा "
            "सहायता नहीं कर सकता।",
        ),
    },
    "fraud_scam": {
        "en": (
            "Let's help you report this safely",
            "I'm sorry this happened. Do NOT share any OTP, PIN, password, or card details "
            "with anyone. Please report the fraud to the official cyber-crime portal. If money "
            "was lost, report it as soon as possible — quick reporting improves recovery chances.",
        ),
        "hi": (
            "आइए इसकी शिकायत सुरक्षित तरीके से दर्ज करें",
            "ऐसा हुआ, इसके लिए खेद है। किसी के साथ कोई OTP, PIN, पासवर्ड या कार्ड जानकारी साझा न करें। "
            "कृपया आधिकारिक साइबर-अपराध पोर्टल पर धोखाधड़ी की शिकायत दर्ज करें। यदि पैसे गए हैं तो "
            "जल्द से जल्द शिकायत करें — जल्दी रिपोर्ट करने से वापसी की संभावना बढ़ती है।",
        ),
    },
    "harmful_instructions": {
        "en": (
            "I can't help with that",
            "I can't help with requests that could cause harm. If you have a legitimate, safe "
            "need behind this, tell me more and I'll try to help within safe limits.",
        ),
        "hi": (
            "मैं इसमें मदद नहीं कर सकता",
            "जो अनुरोध नुकसान पहुँचा सकते हैं, उनमें मैं मदद नहीं कर सकता। यदि इसके पीछे कोई वैध और "
            "सुरक्षित ज़रूरत है, तो अधिक बताएँ — मैं सुरक्षित सीमा में मदद करने की कोशिश करूँगा।",
        ),
    },
}


def _pick(tag: str, language: str) -> tuple[str, str]:
    base = language.split("+")[0]
    msgs = _MESSAGES[tag]
    return msgs.get(base, msgs["en"])


def build_safe_card(tag: str, language: str, correlation_id: str = "") -> dict:
    """Build a supportive ResponseCard for a non-normal safety tag."""
    title, summary = _pick(tag, language)
    resources = crisis_resources(tag)

    sources = []
    for r in resources:
        label = r["name"]
        if r.get("number"):
            label = f"{label}: {r['number']}"
        sources.append({"text": label, "url": r.get("url", "")})

    card = {
        "cardType": "answer",
        "language": language,
        "title": title,
        "summary": summary,
        "sources": sources or None,
        # A safe-path response is never a grounded factual answer; mark it explicitly.
        "safety_tag": tag,
        "abstained": False,
        "correlation_id": correlation_id,
    }
    SAFETY_GATE_TOTAL.labels(outcome="safe_redirect").inc()
    log.info("safe_response_built", tag=tag, language=language, correlation_id=correlation_id)
    return card
