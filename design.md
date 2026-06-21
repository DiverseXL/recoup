# Recoup — UI Design Spec
> Reference: subscription-tracker mobile app screenshots (green/cream palette, card-based, calendar view)

## Goal
Move from a generic dark-mode SaaS dashboard to a warmer, more distinctive visual identity that feels like a personal finance tool, not a devtool. Keep all existing JS logic (`callTool`, `startScan`, `classifyEmailsWithAI`, etc.) untouched — this is a CSS + layout pass only, not a functional rewrite.

---

## 1. Color Palette — Replace Dark Mode With Warm Light Mode

Current: `--bg: #0a0a0f` (near-black), purple/pink accents.
New: lime-green primary, cream/off-white surface, dark green text.

```css
:root {
  --bg: #f4f1ea;            /* warm cream background, not pure white */
  --surface: #ffffff;       /* card background */
  --surface2: #f0f7e8;      /* subtle green-tinted panel */
  --border: #e0ddd2;
  --accent: #8ee000;        /* lime green — primary CTA color, matches reference */
  --accent-dark: #1a2e05;   /* deep green for text on lime backgrounds */
  --text: #1a1f0f;          /* near-black warm text */
  --muted: #6b6f5f;
  --red: #e8473f;           /* urgent / trial-ending */
  --orange: #f5a623;        /* price hike */
  --font: 'Inter', system-ui, sans-serif;
}
```

## 2. Hero Section — Annual Bleed

- Keep the large dollar figure, but change background from dark gradient to **solid lime green** (`--accent`), with **dark green text** (`--accent-dark`) for contrast — not white-on-dark.
- Reduce border-radius slightly increase (16px → 20px) to match the soft, friendly card style in the reference.
- Add a small laurel-wreath-style badge element near the top, text: "Smart Subscription Tracking" (purely decorative, static SVG or emoji-based, no functional change).

## 3. Subscription Cards — Icon-First Layout

Update `renderCard(sub)`:
- Keep existing vendor avatar circle, but switch from purple/pink gradient to **solid pastel color per vendor category** (e.g., generate a consistent pastel hash-color per vendor name string instead of a single gradient).
- Move price to be **inline next to vendor name** (single row: `Netflix · $17.99/mo`), not a separate large heading below.
- Replace urgency badge text ("Trial Ending") with a **circular countdown badge** showing days remaining (e.g., a small ring/circle with "15" + "days" inside, like Image 1's countdown rings) when `next_billing_date` is within 30 days. Fall back to existing text badge style if no near-term date.

## 4. NEW: Monthly Spend Bar Chart

Add a new section below the hero, above "Top Cost Drains":
- If only one scan's worth of data exists (current session), render a **single bar** for the current month labeled with today's month name — still visually consistent, just one data point.
- If `load_subscriptions` returns prior saved history with a different `saved_at` month, render multiple bars (one per distinct month found in storage).
- Each bar: vendor-agnostic total spend for that month, color from a small fixed palette (orange/yellow/blue/green/grey, cycling).
- Show "Monthly Average" as a large number top-right of the chart card, same visual weight as the reference.

Use a simple `<div>`-based CSS bar chart (flexbox columns with height as inline style based on percentage of max) — no charting library needed, keeps bundle dependency-free per Anna's CSP constraints (`script-src 'self'`).

## 5. Subscription Detail — Lightweight Expand, Not Full Page

- Clicking a card's vendor name (not the action buttons) toggles an inline expanded section within the same card showing: `Next billing`, `Annual cost`, `Detected from email on {received_at date}`.
- Rename "Cancel Draft" button to "Mark for Cancellation" + keep existing Gmail compose behavior unchanged.

## 6. Buttons

- Primary actions ("Scan My Gmail", "Protect All") → solid lime green background, dark green text, fully rounded (border-radius: 999px, pill-shaped) — matches reference button style exactly.
- Secondary actions (card-level "Alert Me") → outline style, lime green border, transparent background.

## 7. Typography

- Headlines: bold, slightly oversized, tight letter-spacing (matches reference "Your subscriptions & expenses." style) — increase hero headline from current 64px/800-weight to similar but test at 56-60px to avoid overflow on smaller windows (Anna App UI min_size is 380×560).
- Body text: keep current Inter/system-ui stack, just shift color from light-on-dark to dark-on-cream.

## 8. What NOT To Change

- Do not touch any `<script>` block logic — `callTool`, `startScan`, `classifyEmailsWithAI`, `renderResults`, toast system stay exactly as-is.
- Do not add external fonts/CDN scripts — CSP is `script-src 'self'` per `manifest.json`. Inter should already be a safe system fallback; do not add a Google Fonts `<link>`.
- Do not remove the `needs_review` / `display_note` pattern — keep showing "—" + note for unpriced detections.
- Do not change `manifest.json`, `recoup_plugin.py`, or any backend logic — UI/CSS only.
