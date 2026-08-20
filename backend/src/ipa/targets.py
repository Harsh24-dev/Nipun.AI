"""
Target selection — pick the BEST website/app/software for a task at planning time.

An intelligent IPA shouldn't guess a URL; it should choose the right destination the way a person
would: prefer the official/authoritative service, prefer one the user already uses, prefer an
India-first option, and prefer a site that has WORKED before (a proven recipe). This module gives
the planner a grounded, curated shortlist of candidate targets per task category so its choice is
reliable instead of hallucinated. The LLM still makes the final call (and may pick something better
it knows), but it starts from real options.
"""

from __future__ import annotations

from src.core.logging import get_ipa_logger

log = get_ipa_logger("ipa.targets")

# India-first catalog: task category → ranked candidate targets. `official=True` marks the
# authoritative source (prefer it for anything transactional/government).
CATALOG: dict[str, list[dict]] = {
    "train": [
        {"name": "IRCTC", "url": "https://www.irctc.co.in", "note": "official Indian Railways booking", "official": True},
        {"name": "ConfirmTkt", "url": "https://www.confirmtkt.com", "note": "train search + seat availability"},
        {"name": "RailYatri", "url": "https://www.railyatri.in", "note": "trains, PNR, running status"},
    ],
    "flight": [
        {"name": "MakeMyTrip", "url": "https://www.makemytrip.com/flights", "note": "flights, wide coverage"},
        {"name": "Goibibo", "url": "https://www.goibibo.com/flights", "note": "flights + offers"},
        {"name": "Google Flights", "url": "https://www.google.com/travel/flights", "note": "compare fares"},
    ],
    "hotel": [
        {"name": "MakeMyTrip", "url": "https://www.makemytrip.com/hotels", "note": "hotels across India"},
        {"name": "Booking.com", "url": "https://www.booking.com", "note": "global hotel inventory"},
        {"name": "OYO", "url": "https://www.oyorooms.com", "note": "budget stays in India"},
    ],
    "bus": [
        {"name": "redBus", "url": "https://www.redbus.in", "note": "largest bus booking in India", "official": True},
        {"name": "AbhiBus", "url": "https://www.abhibus.com", "note": "buses + offers"},
    ],
    "jobs": [
        {"name": "Naukri", "url": "https://www.naukri.com", "note": "largest Indian job portal"},
        {"name": "LinkedIn", "url": "https://www.linkedin.com/jobs", "note": "professional roles"},
        {"name": "Indeed", "url": "https://in.indeed.com", "note": "broad job search"},
    ],
    "shopping": [
        {"name": "Amazon.in", "url": "https://www.amazon.in", "note": "widest selection"},
        {"name": "Flipkart", "url": "https://www.flipkart.com", "note": "India-first marketplace"},
    ],
    "food": [
        {"name": "Zomato", "url": "https://www.zomato.com", "note": "food delivery + dining"},
        {"name": "Swiggy", "url": "https://www.swiggy.com", "note": "food + Instamart"},
    ],
    "grocery": [
        {"name": "Blinkit", "url": "https://www.blinkit.com", "note": "quick grocery delivery"},
        {"name": "BigBasket", "url": "https://www.bigbasket.com", "note": "full grocery"},
    ],
    "movies": [
        {"name": "BookMyShow", "url": "https://in.bookmyshow.com", "note": "movies + events", "official": True},
    ],
    "bills": [
        {"name": "Paytm", "url": "https://paytm.com/recharge", "note": "recharge + bill payments"},
        {"name": "BharatNPCI BBPS", "url": "https://www.bharatbillpay.com", "note": "official bill payments", "official": True},
    ],
    "government": [
        {"name": "India.gov.in", "url": "https://www.india.gov.in", "note": "national services portal", "official": True},
        {"name": "UMANG", "url": "https://web.umang.gov.in", "note": "unified govt services", "official": True},
        {"name": "DigiLocker", "url": "https://www.digilocker.gov.in", "note": "official documents", "official": True},
    ],
    "maps": [
        {"name": "Google Maps", "url": "https://www.google.com/maps", "note": "directions + places"},
    ],
    "search": [
        {"name": "Google", "url": "https://www.google.com", "note": "general web search"},
    ],
}

# category → keywords that indicate it.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "train": ("train", "irctc", "rail", "railway", "pnr", "tatkal"),
    "flight": ("flight", "flights", "air ticket", "airfare", "fly to", "plane"),
    "hotel": ("hotel", "stay", "room", "resort", "lodge", "accommodation"),
    "bus": ("bus", "volvo", "sleeper bus", "redbus"),
    "jobs": ("job", "jobs", "vacancy", "hiring", "naukri", "internship", "apply for a role", "career"),
    "shopping": ("buy", "order", "shopping", "purchase", "amazon", "flipkart", "phone", "laptop", "product"),
    "food": ("food", "order food", "restaurant", "zomato", "swiggy", "meal"),
    "grocery": ("grocery", "groceries", "vegetables", "instamart", "bigbasket", "blinkit"),
    "movies": ("movie", "cinema", "film ticket", "bookmyshow", "show ticket"),
    "bills": ("bill", "recharge", "electricity bill", "gas bill", "water bill", "dth", "mobile recharge", "pay bill"),
    "government": ("aadhaar", "pan card", "passport", "voter", "ration", "certificate", "pension", "scheme", "gov.in", "govt", "government"),
    "maps": ("directions", "route to", "nearest", "how to reach", "map"),
}


# TRUST — reputable review / comparison / info sources allowed to appear as options or citations,
# on top of every host already in the CATALOG. Anything NOT on this list is dropped, so we never
# show the user a fake, sketchy, or unknown site that would erode their trust in the app.
_EXTRA_TRUSTED = {
    "google.com", "bing.com", "wikipedia.org", "tripadvisor.in", "tripadvisor.com", "trustpilot.com",
    "mouthshut.com", "justdial.com", "cleartrip.com", "ixigo.com", "yatra.com", "easemytrip.com",
    "paisabazaar.com", "bankbazaar.com", "gadgets360.com", "91mobiles.com", "smartprix.com",
    "cardekho.com", "carwale.com", "magicbricks.com", "99acres.com", "practo.com", "1mg.com",
    "netmeds.com", "pharmeasy.in", "myntra.com", "ajio.com", "nykaa.com", "tatacliq.com",
    "reliancedigital.in", "croma.com", "apollopharmacy.in", "irctc.co.in", "makemytrip.com",
    "goibibo.com", "booking.com", "redbus.in", "naukri.com", "linkedin.com", "indeed.com",
    "amazon.in", "flipkart.com", "zomato.com", "swiggy.com", "bookmyshow.com",
}


def _all_trusted_hosts() -> set[str]:
    from urllib.parse import urlparse
    hosts = set(_EXTRA_TRUSTED)
    for lst in CATALOG.values():
        for c in lst:
            h = urlparse(c["url"]).netloc.replace("www.", "").lower()
            if h:
                hosts.add(h)
    log.debug("trusted_hosts_built", count=len(hosts), extra=len(_EXTRA_TRUSTED))
    return hosts


TRUSTED_HOSTS = _all_trusted_hosts()

log.debug("targets_loaded", categories=len(CATALOG),
          keyword_categories=len(CATEGORY_KEYWORDS), trusted_hosts=len(TRUSTED_HOSTS))


def is_trusted(url: str) -> bool:
    """True only for a known-reputable host — the gate that keeps fake/sketchy sites out of the
    options we show the user."""
    from urllib.parse import urlparse
    try:
        host = urlparse(url or "").netloc.replace("www.", "").lower()
    except Exception as exc:
        log.warning("is_trusted_parse_failed", url=url, error=str(exc),
                    error_type=type(exc).__name__)
        return False
    if not host:
        log.debug("is_trusted", url=url, result=False, reason="no_host")
        return False
    result = any(host == t or host.endswith("." + t) for t in TRUSTED_HOSTS)
    log.debug("is_trusted", host=host, result=result)
    return result


def detect_category(goal: str) -> str | None:
    q = (goal or "").lower()
    best, best_hits = None, 0
    for cat, kws in CATEGORY_KEYWORDS.items():
        hits = sum(1 for k in kws if k in q)
        if hits > best_hits:
            best, best_hits = cat, hits
    log.debug("detect_category", category=best, hits=best_hits)
    return best


def candidates(goal: str) -> list[dict]:
    """Curated candidate targets for a goal (best-first), or a general-search fallback."""
    cat = detect_category(goal)
    if cat and cat in CATALOG:
        log.info("candidates_selected", category=cat, count=len(CATALOG[cat]))
        return CATALOG[cat]
    log.info("candidates_selected", category=cat, count=len(CATALOG["search"]), fallback=True)
    return CATALOG["search"]
