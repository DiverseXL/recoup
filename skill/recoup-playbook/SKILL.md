# Recoup Skill

Recoup helps users find and manage subscription leaks, detect SaaS usage warnings, and set up Google Calendar defenders for trial/billing events.

## When to Invoke

Invoke this skill when the user asks to:
- Find their subscriptions or analyze their spending/billing.
- Scan their Gmail for subscriptions or billing leaks.
- List subscriptions or trials ending soon.
- Set up alerts or calendar reminders for subscription billing or trial expiries.
- Clear subscription history or reset the app data.

## Orchestration Flow

1. **Scan Emails**: Call `scan_gmail_subscriptions` to retrieve raw billing and subscription emails from Gmail.
2. **Classify**: Call `classify_emails` passing the retrieved `emails` array. This tool attempts AI-powered classification via Anna's sampling primitive first, falling back to deterministic pattern matching if sampling is unavailable.
3. **Calculate**: Call `calculate_bleed` passing the classified `subscriptions` array to compute annual bleed, monthly burn, and top cost drains.
4. **Persist Results**: Call `save_subscriptions` with the `subscriptions` array and calculated `annual_bleed` to store the updated history via Anna's Persistent Storage.
5. **Report to User**: Present the results — total annual bleed, active subscription details (vendor, amount, frequency), and any trials needing urgent review.
6. **Defend Calendar**: Offer to write Calendar alerts via `create_bulk_alerts` for upcoming billing dates.

## Tools Reference

### `scan_gmail_subscriptions`
Retrieves raw emails matching subscription/billing query patterns from Gmail.

### `classify_emails`
Classifies raw emails into structured subscription data (vendor, amount, currency, frequency, trial status, urgency). Tries Anna's real LLM sampling first; falls back to deterministic pattern matching if sampling isn't available.

### `calculate_bleed`
Deterministic financial analysis — computes annual bleed, monthly burn, and top cost drains from classified subscription data.

### `save_subscriptions`, `load_subscriptions`
Persists and retrieves subscription history via Anna's real Persistent Storage (APS).

### `create_bulk_alerts`
Creates Google Calendar alerts 48 hours before each subscription's billing date.