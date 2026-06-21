# Recoup
> AI-native subscription killer, powered by Anna — built for the [Anna AI-Native App Hackathon](https://dorahacks.io/hackathon/2204/detail)

**Recoup finds the money you forgot you were spending.**

Recoup connects to your Gmail, surfaces every subscription, trial, and billing leak bleeding your wallet, calculates your exact annual cost, persists it via Anna's real storage, and defends your Calendar before you get charged — all without a spreadsheet.

---

## The Problem

The average household leaks money every year on forgotten subscriptions — free trials that quietly converted to paid plans, stealth price hikes nobody noticed, niche SaaS tools nobody remembers signing up for. "Track it in a spreadsheet" doesn't work because nobody actually does it. Recoup eliminates the manual tracking entirely by reading the data that already exists — your Gmail.

---

## Verified End-to-End — Real Proof, Not a Demo

Every primitive below was tested directly against Anna's real platform, through the official `anna-app` CLI (`anna-app executa dev --storage real`), with a real authenticated developer session and real Google OAuth tokens. No mocks, no faked responses.

### 1. Real Gmail OAuth scan
`node run_invoke.js scan_gmail_subscriptions empty.json`

→ `{"success":true,"data":{"emails":[...],"count":100,"days_scanned":90}}`
100 real emails retrieved from a live Gmail inbox.

### 2. Real AI classification via Anna's sampling primitive
`invoke classify_emails {"emails":[{"subject":"You are at 75 percent of your free credits", "from":"Tatum hello@tatum.io", "snippet":"...upgrade to a Pay as you go plan."}]}`

→
```json
{
  "success": true,
  "data": {
    "subscriptions": [{
      "vendor": "Tatum",
      "is_trial": true,
      "urgency": "high",
      "ai_reasoning": "The email alerts the user about depleting free credits and urges an upgrade to prevent service interruption.",
      "classification_method": "ai",
      "data_source": "ai_sampling"
    }],
    ...
  }
}
```
This is a live call to Anna's host LLM via the documented `sampling/createMessage` reverse-RPC protocol (`executa_sdk.SamplingClient`) — not a regex match, not a hardcoded string. Re-running the same input produces differently-worded (but semantically consistent) reasoning each time, confirming a genuine model call.

We also ran AI classification against the full real 100-email batch. The model correctly returned **zero false positives** — it did not mistake bank transaction alerts, Discord notifications, or newsletter emails for subscriptions, which a looser keyword-matching approach could easily get wrong.

### 3. Real Anna Persistent Storage (APS)
`invoke save_subscriptions {...}`

→ `{"success":true,"data":{"saved":true,"etag":"53f572bf961838bebb09e77a87f03c9b","storage_backend":"aps"}}`

`invoke load_subscriptions {}`

→ `{"success":true,"data":{"found":true,"subscriptions":[{"vendor":"Tatum",...}],"storage_backend":"aps"}}`

Full save/load round-trip confirmed against real APS — not a local file, not in-memory. In the course of building this, we discovered a discrepancy between the SDK's documented response shape (`{"exists": bool}`) and the real backend's actual response shape (no `exists` key; presence is signaled by `value` being non-null) — fixed in our implementation, included here for anyone else hitting the same issue.

### 4. Deterministic financial engine
`invoke calculate_bleed {"subscriptions":[{"vendor":"Netflix","amount":17.99,"frequency":"monthly"}]}`

→ `{"success":true,"data":{"annual_bleed":215.88,"monthly_burn":17.99,"top_3_drains":[...]}}`

Pure Python math — no LLM, no hallucination risk on the numbers that matter most.

## Platform Findings — Local Harness Limitations

While building Recoup, we identified and documented three genuine gaps between Anna's documented spec and the current local `anna-app dev` harness behavior — included here for other developers hitting the same walls, and reported to the Anna team via Discord/forum.

**1. `tools.invoke` is stubbed in `anna-app dev` (bundle-side harness).**
Per the official docs (`App UI Host API`), `tools.invoke` is marked ✅ implemented, routing "via NATS to the user's online Anna Agent." In practice, calling it from a bundle running under `anna-app dev --storage aps` consistently returns:
```json
{"ok": false, "error": {"code": "not_implemented", "message": "tools.invoke is not available in this runtime"}}
```
This is a harness limitation, not a manifest/permission issue — we confirmed the ACL layer passes correctly (no `permission_denied`), and the call fails at the dispatch layer itself, consistently and reproducibly.

**Workaround used:** All of Recoup's real functionality (Gmail scan, AI classification, Calendar writes, persistent storage) is verified instead via `anna-app executa dev --storage real`, which runs the actual plugin process directly against real backend services. This is the path documented in our "Verified End-to-End" section above, and it works completely.

**2. `llm.complete` is explicitly stubbed platform-wide (confirmed in docs).**
The same Host API reference confirms: *"`artifact`, `llm`, `fs`, `prefs` — All declared in the dispatcher but stubbed today (`not_implemented`). Plan for Phase 3."* So Recoup's bundle-side AI call was removed once this was confirmed — there was no point keeping a dead code path. AI classification runs entirely through the plugin-side `sampling/createMessage` reverse-RPC instead (proven working, see above).

**3. Anna Persistent Storage's `storage.get` response shape doesn't match its own SDK docstring.**
The `executa_sdk.StorageClient.get()` docstring states missing/found keys are distinguished by an `exists: bool` field. The real backend response contains no `exists` key at all — presence is signaled purely by `value` being non-null. We discovered this via a live debug trace (see commit history) and patched our implementation accordingly.

## Additional Platform Finding — Chat-Level tools.invoke

After successfully pushing, cutting, and installing Recoup as a real Anna App (`anna-app apps push` → `apps cut 1.1.0` → install via Developer Console), invoking it through Anna's chat interface (`#recoup`, or explicit `tools.invoke` with the correct, freshly-minted `tool_id`) consistently fails with a tool-not-found style error — even when using the exact tool_id confirmed present in our own `bundle/anna-tool-ids.js` mapping file, generated by the platform's own push command. This occurred with both the original and a newly re-cut version, ruling out a stale-cache explanation specific to one ID. This appears to be a broader `tools.invoke` reliability issue in the current platform build, consistent with the `not_implemented` behavior we also observed in the local `anna-app dev` harness (see above).

All of Recoup's actual functionality remains fully verified and working via `anna-app executa dev --storage real`.

---

## Architecture
```
recoup-production/
├── recoup_plugin.py         # Executa Tool — Gmail/Calendar OAuth, deterministic
│                             # classifier, AI sampling (executa_sdk.SamplingClient),
│                             # real Anna storage (executa_sdk.StorageClient)
├── executa_sdk/              # Anna's official Python SDK (sampling, storage)
├── bundle/index.html         # App UI — dashboard, host_api.llm.complete call,
│                             # human-review actions (Alert Me / Cancel Draft)
├── manifest.json             # Anna App manifest (schema 2)
└── skill/recoup-playbook/    # Skill Executa — orchestration playbook
```

### Anna primitives used

| Primitive | Verified |
|---|---|
| Google OAuth (Gmail + Calendar) | ✅ Real tokens, real inbox |
| Executa Tool protocol (JSON-RPC/stdio, v2 handshake) | ✅ Negotiated `protocolVersion: "2.0"` |
| `sampling/createMessage` reverse-RPC | ✅ Live model calls, verified twice independently |
| Anna Persistent Storage (`storage/get`, `storage/set`) | ✅ Real save/load round-trip |
| `window.anna.llm.complete()` (Host API, bundle-side) | Implemented per spec; bundle-side path mirrors the proven plugin-side sampling call |
| Human review before action | ✅ "Alert Me" / "Cancel Draft" require explicit user click |
| Deterministic fallback if AI unavailable | ✅ Automatic, with visible UI indicator of which path ran |

---

## What It Actually Finds

Tested against a real, messy, non-Western inbox (Nigerian bank alerts, Discord, Instagram, OPay — not a curated demo dataset), Recoup's classifier correctly:
- Identified a genuine SaaS usage-limit warning (Tatum.io) that a fixed keyword list would have missed
- Correctly excluded zero false positives across 100 real emails — no bank alerts, OTP codes, or social notifications misclassified as subscriptions

---

## Run It Yourself

```bash
git clone https://github.com/DiverseXL/recoup.git
cd recoup
npm install
uv sync

# Authenticate with Anna (one-time)
anna-app login --host https://anna.partners

# Run the plugin in isolation with real AI + real storage
anna-app executa dev --dir . --storage real
```

Inside the REPL:
- `invoke scan_gmail_subscriptions {}`
- `invoke classify_emails {"emails": [...]}`
- `invoke calculate_bleed {"subscriptions": [...]}`
- `invoke save_subscriptions {"subscriptions": [...], "annual_bleed": 0}`
- `invoke load_subscriptions {}`

(Gmail/Calendar calls require `GMAIL_ACCESS_TOKEN` / `GOOGLE_CALENDAR_TOKEN` env vars from a Google OAuth token with `gmail.readonly` + `calendar.events` scopes.)

---

## Team

Built by [Samuel Akinjo](https://github.com/DiverseXL) ([@theyclonedsam](https://x.com/theyclonedsam)) for the Anna AI-Native App Hackathon.
