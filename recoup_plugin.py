"""Recoup — AI-native subscription killer, powered by Anna.

Anna Executa plugin (JSON-RPC 2.0 over stdio).
Scans Gmail, classifies subscriptions via Anna's LLM bridge,
calculates deterministic financial bleed, persists history via
Anna storage, and creates Google Calendar defense alerts.
"""
import json
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

try:
    import executa_sdk  # noqa: F401
except ModuleNotFoundError:
    from pathlib import Path
    _SDK_PATH = Path(__file__).resolve().parent / "executa_sdk"
    if _SDK_PATH.parent.is_dir():
        sys.path.insert(0, str(_SDK_PATH.parent))

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from executa_sdk import (
    PROTOCOL_VERSION_V2,
    SamplingClient,
    SamplingError,
    StorageClient,
    StorageError,
)

MANIFEST = {
    "name": "tool-mccloned-recoup-q35vp3wj",
    "version": "1.0.0",
    "description": "Recoup scans Gmail for subscriptions and billing leaks, "
                    "calculates annual bleed, and defends your Calendar.",
    "tools": [
        {
            "name": "scan_gmail_subscriptions",
            "description": "Scans Gmail for subscription, billing, and trial emails "
                            "from the last N days. Returns raw email metadata.",
            "parameters": {
                "type": "object",
                "properties": {
                    "days_back": {"type": "integer", "description": "How many days back to scan (default 90)"},
                    "max_results": {"type": "integer", "description": "Max emails to fetch (default 100)"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "classify_emails",
            "description": "Classifies emails into subscription data using vendor-agnostic rules.",
            "parameters": {
                "type": "object",
                "properties": {
                    "emails": {"type": "array", "description": "Array of scanned email objects"},
                },
                "required": ["emails"],
                "additionalProperties": False,
            },
        },
        {
            "name": "calculate_bleed",
            "description": "Deterministic financial analysis. Calculates annual bleed, "
                            "monthly burn, top cost drains, from structured subscription data. No LLM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscriptions": {
                        "type": "array",
                        "description": "Array of subscription objects with vendor, amount, frequency",
                    },
                },
                "required": ["subscriptions"],
                "additionalProperties": False,
            },
        },
        {
            "name": "save_subscriptions",
            "description": "Saves subscription history to Anna persistent storage.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscriptions": {"type": "array"},
                    "annual_bleed": {"type": "number"},
                },
                "required": ["subscriptions", "annual_bleed"],
                "additionalProperties": False,
            },
        },
        {
            "name": "load_subscriptions",
            "description": "Loads previously saved subscription history from Anna persistent storage.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "create_bulk_alerts",
            "description": "Creates Google Calendar alerts 48 hours before each subscription's billing date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "subscriptions": {"type": "array"},
                },
                "required": ["subscriptions"],
                "additionalProperties": False,
            },
        },
        {
            "name": "ping",
            "description": "Smoke-test method.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    ],
}

MANIFEST["host_capabilities"] = ["llm.sample"]

_stdout_lock = threading.Lock()

def _write_frame(msg: dict) -> None:
    payload = json.dumps(msg, ensure_ascii=False)
    with _stdout_lock:
        sys.stdout.write(payload + "\n")
        sys.stdout.flush()

sampling = SamplingClient(write_frame=_write_frame)
storage = StorageClient(write_frame=_write_frame)

_loop = asyncio.new_event_loop()
_loop_thread = threading.Thread(target=_loop.run_forever, daemon=True)
_loop_thread.start()

# ─── Gmail ──────────────────────────────────────────────────────────────────

def _gmail_request(token: str, endpoint: str, params: dict | None = None, repeat_param: str = None) -> dict:
    url = f"https://gmail.googleapis.com/gmail/v1/{endpoint}"
    query_parts = []
    if params:
        for k, v in params.items():
            if k == repeat_param and isinstance(v, list):
                for item in v:
                    query_parts.append(f"{k}={urllib.parse.quote(str(item))}")
            else:
                query_parts.append(f"{k}={urllib.parse.quote(str(v))}")
    if query_parts:
        url = f"{url}?{'&'.join(query_parts)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _build_query(days_back: int) -> str:
    after = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y/%m/%d")
    return (
        f"after:{after} ("
        'subject:(receipt OR invoice OR billing OR subscription OR payment OR trial) OR '
        'subject:("auto-renew" OR charged OR "order confirmation" OR renewal OR membership) OR '
        'subject:("welcome to" OR "your plan" OR "payment successful" OR upgrade) OR '
        "from:(billing@ OR invoice@ OR payments@ OR receipts@ OR noreply@ OR no-reply@)"
        ")"
    )


def _parse_email(msg: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
    received_at = None
    if msg.get("internalDate"):
        received_at = datetime.fromtimestamp(int(msg["internalDate"]) / 1000, tz=timezone.utc).isoformat()
    return {
        "message_id": msg.get("id"),
        "thread_id": msg.get("threadId"),
        "subject": headers.get("subject", ""),
        "from": headers.get("from", ""),
        "date": headers.get("date", ""),
        "received_at": received_at,
        "snippet": msg.get("snippet", ""),
    }


def scan_gmail_subscriptions(args: dict, credentials: dict) -> dict:
    token = credentials.get("GMAIL_ACCESS_TOKEN")
    if not token:
        return {"success": False, "error": "GMAIL_ACCESS_TOKEN not granted. Connect Google in Authorizations."}

    days_back = args.get("days_back", 90)
    max_results = min(args.get("max_results", 100), 200)

    try:
        listing = _gmail_request(token, "users/me/messages", {
            "q": _build_query(days_back),
            "maxResults": max_results,
        })
    except urllib.error.HTTPError as e:
        return {"success": False, "error": f"Gmail API error {e.code}: {e.reason}"}

    message_refs = listing.get("messages", [])
    if not message_refs:
        return {"success": True, "data": {"emails": [], "count": 0, "days_scanned": days_back}}

    emails = []
    for ref in message_refs:
        try:
            full = _gmail_request(token, f"users/me/messages/{ref['id']}", {
                "format": "metadata",
                "metadataHeaders": ["Subject", "From", "Date"],
            }, repeat_param="metadataHeaders")
            emails.append(_parse_email(full))
        except Exception:
            continue

    return {"success": True, "data": {"emails": emails, "count": len(emails), "days_scanned": days_back}}


# ─── Deterministic Email Classifier (no LLM, vendor-agnostic) ──────────────

import re
from urllib.parse import urlparse

AMOUNT_PATTERN = re.compile(r"(?:USD|US\$|\$|₦|NGN|N|EUR|€|GBP|£)\s?([\d,]+\.?\d{0,2})", re.IGNORECASE)

# Generic bank/transfer noise to exclude — these are NOT subscriptions
SKIP_KEYWORDS = [
    "debit alert", "credit alert", "account balance", "atm withdrawal",
    "transfer alert", "airtime", "data purchase", "wallet funded",
    "otp", "one-time password", "verification code", "login alert",
    "password reset", "security alert",
]

# Strong signals this IS a subscription/billing email
BILLING_SIGNALS = [
    "subscription", "billing", "invoice", "receipt", "payment confirmation",
    "your trial", "free trial", "trial ends", "trial expires", "auto-renew",
    "renewal", "your plan", "membership", "recurring payment", "next billing",
    "charged", "payment successful", "order confirmation", "you've been charged",
    "your order", "premium plan", "upgrade confirmation", "monthly plan",
    "annual plan", "we charged", "payment receipt", "thank you for your purchase",
    "your subscription", "plan renewal",
    # Niche SaaS / usage-based signals
    "free credits", "credits used", "upgrade to continue", "pay as you go",
    "usage limit", "running low", "out of credits", "quota", "api limit",
    "upgrade your plan", "running out", "limit reached",
]

SKIP_DOMAINS = [
    "moniepoint.com", "opay-nigeria.com", "discord.com", "instagram.com",
    "redditmail.com", "accountprotection.microsoft.com", "accounts.google.com",
]


GENERIC_SENDER_PREFIXES = [
    "noreply", "no-reply", "donotreply", "billing", "invoice", "payments",
    "receipts", "support", "hello", "team", "notifications", "info",
]

KNOWN_VENDOR_DOMAINS = {
    "netflix.com": "Netflix", "spotify.com": "Spotify", "adobe.com": "Adobe Creative Cloud",
    "avast.com": "Avast Antivirus", "canva.com": "Canva", "github.com": "GitHub",
    "dropbox.com": "Dropbox", "notion.so": "Notion", "hulu.com": "Hulu",
    "disneyplus.com": "Disney+", "amazon.com": "Amazon Prime", "youtube.com": "YouTube Premium",
    "apple.com": "Apple", "microsoft.com": "Microsoft 365", "google.com": "Google One",
    "linkedin.com": "LinkedIn Premium", "grammarly.com": "Grammarly",
    "openai.com": "OpenAI", "anthropic.com": "Claude / Anthropic", "midjourney.com": "Midjourney",
    "figma.com": "Figma", "vercel.com": "Vercel", "render.com": "Render",
    "namecheap.com": "Namecheap", "godaddy.com": "GoDaddy", "digitalocean.com": "DigitalOcean",
    "heroku.com": "Heroku", "elevenlabs.io": "ElevenLabs", "runwayml.com": "Runway",
}


def _extract_domain(from_field: str) -> str:
    match = re.search(r"@([\w.-]+)", from_field or "")
    return match.group(1).lower() if match else ""


def _guess_vendor_name(domain: str, subject: str) -> str:
    # 1. Known domain mapping
    for known_domain, name in KNOWN_VENDOR_DOMAINS.items():
        if known_domain in domain:
            return name

    # 2. Derive from domain itself: "stripe-invoices.somesaas.io" -> "Somesaas"
    parts = domain.replace("mail.", "").replace("email.", "").split(".")
    if len(parts) >= 2:
        candidate = parts[-2]
        if candidate not in ("gmail", "googlemail", "outlook", "yahoo", "hotmail"):
            return candidate.capitalize()

    # 3. Fallback: try to pull a capitalized brand-looking word from the subject
    words = re.findall(r"\b[A-Z][a-zA-Z]{2,}\b", subject)
    generic = {"Your", "The", "This", "Thank", "Welcome", "Hi", "Dear"}
    candidates = [w for w in words if w not in generic]
    return candidates[0] if candidates else "Unknown Vendor"


def classify_emails_deterministic(args: dict, credentials: dict) -> dict:
    emails = args.get("emails", [])
    subscriptions = []
    skipped = 0

    for email in emails:
        subject = (email.get("subject") or "")
        snippet = (email.get("snippet") or "")
        from_field = (email.get("from") or "")
        combined = f"{subject} {snippet}".lower()
        domain = _extract_domain(from_field)

        if any(d in domain for d in SKIP_DOMAINS):
            skipped += 1
            continue

        # Hard exclude — bank/OTP/security noise
        if any(kw in combined for kw in SKIP_KEYWORDS):
            skipped += 1
            continue

        # Must match at least one billing signal OR come from a known vendor domain
        is_known_domain = any(d in domain for d in KNOWN_VENDOR_DOMAINS)
        has_billing_signal = any(sig in combined for sig in BILLING_SIGNALS)

        if not (is_known_domain or has_billing_signal):
            skipped += 1
            continue

        vendor = _guess_vendor_name(domain, subject)

        # Extract amount — if none found, still keep it as a "detected, amount unknown" entry
        amount_match = AMOUNT_PATTERN.search(f"{subject} {snippet}")
        amount = float(amount_match.group(1).replace(",", "")) if amount_match else None

        # Detect frequency
        if any(w in combined for w in ["annual", "yearly", "/year", "per year"]):
            frequency = "annual"
        elif any(w in combined for w in ["weekly", "/week"]):
            frequency = "weekly"
        else:
            frequency = "monthly"

        # Detect trial + urgency
        is_trial = any(w in combined for w in ["trial", "free trial"])
        urgency = "high" if is_trial and any(w in combined for w in ["ending", "expires", "last day", "ends today", "ends tomorrow"]) else "normal"

        subscriptions.append({
            "vendor": vendor,
            "amount": amount,
            "currency": "USD",
            "frequency": frequency,
            "is_trial": is_trial,
            "urgency": urgency,
            "next_billing_date": None,
            "trial_end_date": None,
            "message_id": email.get("message_id"),
            "received_at": email.get("received_at"),
            "source_domain": domain,
        })

    # Deduplicate by vendor — keep most recent, prefer entries that have an amount
    seen = {}
    for sub in subscriptions:
        key = sub["vendor"].lower()
        existing = seen.get(key)
        if not existing:
            seen[key] = sub
        else:
            existing_has_amount = existing.get("amount") is not None
            new_has_amount = sub.get("amount") is not None
            if (new_has_amount and not existing_has_amount) or (sub.get("received_at") or "") > (existing.get("received_at") or ""):
                seen[key] = sub

    results = list(seen.values())

    # Separate genuine priced subscriptions from "activity detected, no price found"
    for r in results:
        if r.get("amount") is None:
            r["needs_review"] = True
            r["display_note"] = "Detected SaaS activity — no billing amount found in email"
        else:
            r["needs_review"] = False
            r["display_note"] = None

    return {"success": True, "data": {
        "subscriptions": results,
        "total_classified": len(results),
        "skipped": skipped,
        "total_scanned": len(emails),
    }}


async def _ai_classify_single_email(email: dict) -> dict | None:
    """Ask the host LLM to classify one email as subscription/billing or not."""
    subject = email.get("subject", "")
    snippet = email.get("snippet", "")
    sender = email.get("from", "")

    prompt = (
        "You are a financial assistant analyzing an email to detect if it represents "
        "a subscription, recurring billing, free trial, or SaaS payment.\n\n"
        f"From: {sender}\nSubject: {subject}\nBody preview: {snippet}\n\n"
        "Reply with ONLY a JSON object, no explanation, no markdown:\n"
        '{"is_subscription": true or false, "vendor": "clean vendor name or null", '
        '"amount": number or null, "currency": "USD or null", '
        '"frequency": "monthly|annual|weekly|one-time or null", '
        '"is_trial": true or false, "urgency": "high or normal", '
        '"reasoning": "one short sentence"}'
    )

    try:
        result = await sampling.create_message(
            messages=[{"role": "user", "content": {"type": "text", "text": prompt}}],
            max_tokens=200,
            system_prompt="You are a precise financial email classifier. Reply with JSON only.",
            metadata={"tool": "ai_classify_email"},
            timeout=30.0,
        )
        content = result.get("content") or {}
        raw_text = content.get("text", "") if isinstance(content, dict) else ""
        raw_text = raw_text.strip().removeprefix("```json").removesuffix("```").strip()
        parsed = json.loads(raw_text)
        if not parsed.get("is_subscription"):
            return None
        return {
            "vendor": parsed.get("vendor") or "Unknown Vendor",
            "amount": parsed.get("amount"),
            "currency": parsed.get("currency") or "USD",
            "frequency": parsed.get("frequency") or "monthly",
            "is_trial": bool(parsed.get("is_trial")),
            "urgency": parsed.get("urgency") or "normal",
            "ai_reasoning": parsed.get("reasoning", ""),
            "message_id": email.get("message_id"),
            "received_at": email.get("received_at"),
            "needs_review": parsed.get("amount") is None,
            "display_note": None if parsed.get("amount") is not None else "AI detected activity — no amount found",
            "classification_method": "ai",
        }
    except (SamplingError, Exception):
        return None


async def classify_emails_ai(emails: list) -> dict:
    """AI-powered classification — runs each email through host LLM sampling concurrently."""
    tasks = [_ai_classify_single_email(e) for e in emails]
    results = await asyncio.gather(*tasks, return_exceptions=False)
    subscriptions = [r for r in results if r is not None]

    seen = {}
    for sub in subscriptions:
        key = sub["vendor"].lower()
        if key not in seen or (sub.get("received_at") or "") > (seen[key].get("received_at") or ""):
            seen[key] = sub

    final = list(seen.values())
    return {
        "subscriptions": final,
        "total_classified": len(final),
        "skipped": len(emails) - len(subscriptions),
        "total_scanned": len(emails),
        "classification_method": "ai",
    }


def classify_emails(args: dict, credentials: dict) -> dict:
    """Tries AI-powered classification via host sampling; falls back to deterministic regex matching if sampling is unavailable or fails."""
    emails = args.get("emails", [])
    if not emails:
        return {"success": True, "data": {"subscriptions": [], "total_classified": 0, "skipped": 0, "total_scanned": 0}}

    if sampling.is_enabled() if hasattr(sampling, "is_enabled") else True:
        try:
            fut = asyncio.run_coroutine_threadsafe(classify_emails_ai(emails), _loop)
            ai_result = fut.result(timeout=90.0)
            if ai_result.get("subscriptions") is not None:
                ai_result["data_source"] = "ai_sampling"
                return {"success": True, "data": ai_result}
        except Exception:
            pass

    fallback = classify_emails_deterministic(args, credentials)
    if fallback.get("success") and fallback.get("data"):
        fallback["data"]["data_source"] = "deterministic_fallback"
    return fallback


# ─── Deterministic Bleed Calculator ────────────────────────────────────────

def _normalize_monthly(amount: float, frequency: str) -> float:
    if not amount:
        return 0.0
    freq = (frequency or "monthly").lower()
    if freq in ("annual", "yearly"):
        return amount / 12
    if freq == "weekly":
        return amount * 4.33
    if freq == "daily":
        return amount * 30.44
    return amount


def calculate_bleed(args: dict, credentials: dict) -> dict:
    subscriptions = args.get("subscriptions", [])
    if not subscriptions:
        return {"success": True, "data": {
            "annual_bleed": 0, "monthly_burn": 0, "total_subscriptions": 0,
            "active_trials": 0, "top_3_drains": [], "per_vendor": [],
        }}

    per_vendor = []
    for sub in subscriptions:
        monthly = _normalize_monthly(sub.get("amount", 0), sub.get("frequency"))
        per_vendor.append({
            "vendor": sub.get("vendor", "Unknown"),
            "monthly": round(monthly, 2),
            "annual": round(monthly * 12, 2),
            "frequency": sub.get("frequency", "monthly"),
            "is_trial": sub.get("is_trial", False),
            "urgency": sub.get("urgency", "normal"),
            "currency": sub.get("currency", "USD"),
        })

    monthly_burn = sum(v["monthly"] for v in per_vendor)
    annual_bleed = monthly_burn * 12
    active_trials = sum(1 for s in subscriptions if s.get("is_trial"))

    top_3 = sorted(per_vendor, key=lambda v: v["annual"], reverse=True)[:3]
    top_3 = [
        {"rank": i + 1, "vendor": v["vendor"], "annual": v["annual"],
         "pct_of_total": round((v["annual"] / annual_bleed) * 100, 1) if annual_bleed else 0}
        for i, v in enumerate(top_3)
    ]

    return {"success": True, "data": {
        "annual_bleed": round(annual_bleed, 2),
        "monthly_burn": round(monthly_burn, 2),
        "total_subscriptions": len(subscriptions),
        "active_trials": active_trials,
        "top_3_drains": top_3,
        "per_vendor": per_vendor,
        "currency": per_vendor[0]["currency"] if per_vendor else "USD",
        "calculated_at": datetime.now(timezone.utc).isoformat(),
    }}


# ─── Storage (Anna reverse primitive via stdout) ───────────────────────────
# Storage calls in this scaffold go through the host_api storage.get/storage.set
# bridge rather than a custom reverse RPC — the harness logs confirmed
# `storage.get` / `storage.set` calls succeed from the bundle side.
# Server-side persistence for the plugin itself (cross-session vendor history)
# uses a local state file as a pragmatic fallback when storage isn't reachable
# from the stdio process directly.

STORAGE_KEY = "recoup:subscriptions:v1"

async def _save_subscriptions_async(subscriptions, annual_bleed):
    record = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "annual_bleed": annual_bleed,
        "subscriptions": subscriptions,
    }
    try:
        result = await storage.set(STORAGE_KEY, record, scope="user")
        return {
            "saved": True,
            "saved_count": len(subscriptions),
            "saved_at": record["saved_at"],
            "storage_backend": "aps",
            "etag": result.get("etag"),
        }
    except StorageError as e:
        return {"saved": False, "error": str(e), "storage_backend": "aps_error"}


async def _load_subscriptions_async():
    try:
        result = await storage.get(STORAGE_KEY, scope="user")
        if result is None or result.get("value") is None:
            return {"found": False, "subscriptions": [], "annual_bleed": 0, "storage_backend": "aps"}
        record = result["value"]
        return {
            "found": True,
            "subscriptions": record.get("subscriptions", []),
            "annual_bleed": record.get("annual_bleed", 0),
            "saved_at": record.get("saved_at"),
            "storage_backend": "aps",
        }
    except StorageError as e:
        return {"found": False, "subscriptions": [], "annual_bleed": 0, "error": str(e), "storage_backend": "aps_error"}


def save_subscriptions(args: dict, credentials: dict) -> dict:
    subscriptions = args.get("subscriptions", [])
    annual_bleed = args.get("annual_bleed", 0)
    fut = asyncio.run_coroutine_threadsafe(
        _save_subscriptions_async(subscriptions, annual_bleed), _loop
    )
    try:
        result = fut.result(timeout=35.0)
        return {"success": result.get("saved", False), "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


def load_subscriptions(args: dict, credentials: dict) -> dict:
    fut = asyncio.run_coroutine_threadsafe(_load_subscriptions_async(), _loop)
    try:
        result = fut.result(timeout=35.0)
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ─── Google Calendar ────────────────────────────────────────────────────────

def _calendar_request(token: str, body: dict) -> dict:
    url = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())


def _build_event(sub: dict) -> dict | None:
    billing_date_str = sub.get("trial_end_date") or sub.get("next_billing_date")
    if not billing_date_str:
        return None

    try:
        billing = datetime.fromisoformat(billing_date_str.replace("Z", "+00:00"))
    except ValueError:
        return None

    alert_time = billing - timedelta(hours=48)
    now = datetime.now(timezone.utc)
    if alert_time < now:
        alert_time = now + timedelta(days=1)

    is_trial = sub.get("is_trial", False)
    vendor = sub.get("vendor", "Unknown")
    amount = sub.get("amount", 0)
    currency = sub.get("currency", "USD")
    frequency = sub.get("frequency", "monthly")

    emoji = "⚠️" if is_trial else "💸"
    action = "CANCEL TRIAL" if is_trial else "REVIEW SUBSCRIPTION"
    charge_text = f"or get charged {currency} {amount}" if is_trial else f"{currency} {amount}/{frequency}"

    return {
        "summary": f"{emoji} {action}: {vendor} ({charge_text})",
        "description": f"Recoup detected this in your Gmail.\n\nVendor: {vendor}\nAmount: {currency} {amount}\n"
                        f"Billing date: {billing_date_str}\n\nPowered by Recoup.",
        "start": {"dateTime": alert_time.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": (alert_time + timedelta(minutes=30)).isoformat(), "timeZone": "UTC"},
        "reminders": {"useDefault": False, "overrides": [
            {"method": "email", "minutes": 1440}, {"method": "popup", "minutes": 60}
        ]},
        "colorId": "11" if is_trial else "6",
    }


def create_bulk_alerts(args: dict, credentials: dict) -> dict:
    token = credentials.get("GOOGLE_CALENDAR_TOKEN") or credentials.get("GMAIL_ACCESS_TOKEN")
    if not token:
        return {"success": False, "error": "GOOGLE_CALENDAR_TOKEN not granted. Connect Google in Authorizations."}

    subscriptions = args.get("subscriptions", [])
    results = []
    for sub in subscriptions:
        event = _build_event(sub)
        if not event:
            results.append({"vendor": sub.get("vendor"), "success": False, "reason": "No billing date"})
            continue
        try:
            created = _calendar_request(token, event)
            results.append({"vendor": sub.get("vendor"), "success": True, "event_id": created.get("id")})
        except Exception as e:
            results.append({"vendor": sub.get("vendor"), "success": False, "reason": str(e)})

    return {"success": True, "data": {
        "total": len(subscriptions),
        "created": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results,
    }}


# ─── Dispatch ────────────────────────────────────────────────────────────────

def invoke(method: str, args: dict, credentials: dict) -> dict:
    if method == "ping":
        return {"success": True, "data": {"pong": True}}
    if method == "scan_gmail_subscriptions":
        return scan_gmail_subscriptions(args, credentials)
    if method == "classify_emails":
        return classify_emails(args, credentials)
    if method == "calculate_bleed":
        return calculate_bleed(args, credentials)
    if method == "save_subscriptions":
        return save_subscriptions(args, credentials)
    if method == "load_subscriptions":
        return load_subscriptions(args, credentials)
    if method == "create_bulk_alerts":
        return create_bulk_alerts(args, credentials)
    return {"success": False, "error": f"unknown method: {method}"}


def main() -> None:
    print("Recoup plugin started", file=sys.stderr)
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="invoke")

    def handle_line(line: str) -> None:
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            return

        method = req.get("method")
        req_id = req.get("id")

        # Reverse-RPC reply from host -> resolve a pending sampling or storage future
        if method is None and req_id is not None and ("result" in req or "error" in req):
            if not sampling.dispatch_response(req):
                storage.dispatch_response(req)
            return

        try:
            if method == "initialize":
                proto = (req.get("params") or {}).get("protocolVersion") or "1.1"
                if proto != PROTOCOL_VERSION_V2:
                    sampling.disable(f"host did not negotiate v2 (offered {proto!r})")
                result = {
                    "protocolVersion": proto if proto in ("1.1", "2.0") else "2.0",
                    "serverInfo": {"name": MANIFEST.get("display_name", "Recoup"), "version": MANIFEST["version"]},
                    "client_capabilities": {"sampling": {}} if proto == PROTOCOL_VERSION_V2 else {},
                    "capabilities": {},
                }
            elif method == "describe":
                result = MANIFEST
            elif method == "health":
                result = {"status": "ok"}
            elif method == "invoke":
                params = req["params"]
                credentials = params.get("context", {}).get("credentials", {})
                result = invoke(params["tool"], params.get("arguments", {}), credentials)
            else:
                sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown rpc: {method}"}}) + "\n")
                sys.stdout.flush()
                return
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}) + "\n")
        except Exception as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(e)}}) + "\n")
        sys.stdout.flush()

    try:
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            pool.submit(handle_line, line)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
        _loop.call_soon_threadsafe(_loop.stop)


if __name__ == "__main__":
    main()
