/**
 * Recoup — Anna App bundle entry point.
 * Wires the dashboard UI to real tool calls via anna.tools.invoke.
 */
import { AnnaAppRuntime } from "/static/anna-apps/_sdk/latest/index.js";

const TOOL_ID = "tool-dev-recoup";

// ─── Helpers ────────────────────────────────────────────────────────────────

function $(id) { return document.getElementById(id); }

function log(msg, type = "info") {
  const area = $("log-area");
  area.classList.add("visible");
  const line = document.createElement("div");
  line.className = `log-${type}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
  area.appendChild(line);
  area.scrollTop = area.scrollHeight;
}

function setStatus(state, label) {
  $("dot").className = `status-dot ${state}`;
  $("status-label").textContent = label;
}

function fmt(n, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency, minimumFractionDigits: 2 }).format(n);
}

function setScanBtnState(busy) {
  const btn = $("scan-btn");
  btn.disabled = busy;
  $("scan-btn-inner").innerHTML = busy
    ? `<span class="spinner"></span> Scanning…`
    : "🔍 Scan Gmail";
}

// ─── Render functions ────────────────────────────────────────────────────────

function renderStats(bleed) {
  $("stats-row").style.display = "grid";
  $("stat-annual").textContent  = fmt(bleed.annual_bleed, bleed.currency);
  $("stat-monthly").textContent = fmt(bleed.monthly_burn, bleed.currency);
  $("stat-count").textContent   = bleed.total_subscriptions;
  $("stat-trials").textContent  = bleed.active_trials;
  $("stat-count-sub").textContent = `subscription${bleed.total_subscriptions !== 1 ? "s" : ""} detected`;
}

function renderDrains(top3, currency) {
  $("drains-card").style.display = "block";
  const fillClasses = ["drain-fill-1", "drain-fill-2", "drain-fill-3"];
  $("drains-body").innerHTML = top3.map((d, i) => `
    <div class="drain-bar">
      <div class="drain-rank">${d.rank}</div>
      <div class="drain-info">
        <div class="drain-name">${d.vendor}</div>
        <div class="drain-track">
          <div class="drain-fill ${fillClasses[i]}" style="width:${d.pct_of_total}%"></div>
        </div>
      </div>
      <div class="drain-amount">${fmt(d.annual, currency)}/yr</div>
    </div>
  `).join("");
}

function renderTable(perVendor, currency) {
  $("subs-card").style.display = "block";
  $("alerts-btn").parentElement.style.display = "flex";

  $("subs-body").innerHTML = perVendor.map(v => {
    const badgeClass = v.is_trial ? "badge-trial" : v.urgency === "urgent" ? "badge-urgent" : "badge-active";
    const badgeText  = v.is_trial ? "Trial" : v.urgency === "urgent" ? "Urgent" : "Active";
    return `
      <tr>
        <td style="font-weight:500">${v.vendor}</td>
        <td>${fmt(v.monthly, v.currency)}/mo</td>
        <td style="color:var(--muted)">${v.frequency}</td>
        <td style="font-weight:600">${fmt(v.annual, v.currency)}</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
      </tr>
    `;
  }).join("");
}

// ─── Mock fallback (when Anna host isn't present) ────────────────────────────

function getMockSubscriptions() {
  return [
    { vendor: "Netflix",    amount: 17.99, frequency: "monthly", is_trial: false, currency: "USD" },
    { vendor: "Adobe CC",   amount: 54.99, frequency: "monthly", is_trial: false, currency: "USD" },
    { vendor: "Spotify",    amount: 9.99,  frequency: "monthly", is_trial: false, currency: "USD" },
    { vendor: "Avast",      amount: 39.99, frequency: "annual",  is_trial: true,  currency: "USD" },
    { vendor: "Notion",     amount: 8.00,  frequency: "monthly", is_trial: false, currency: "USD" },
  ];
}

// ─── Core tool call wrapper ──────────────────────────────────────────────────

let anna = null;

async function callTool(name, args = {}) {
  const sdk = window.anna || anna;
  if (sdk?.tools?.invoke) {
    const response = await sdk.tools.invoke({
      tool_id: TOOL_ID,
      method: name,
      args: args,
    });
    if (response.success === false) {
      throw new Error(response.error || "Tool call failed");
    }
    return response.data ?? response;
  }
  throw new Error("Anna SDK not available — mock-sdk.js may not have loaded");
}

// ─── Main scan flow ──────────────────────────────────────────────────────────

let lastSubscriptions = [];

async function runScan() {
  setScanBtnState(true);
  setStatus("busy", "Scanning Gmail…");
  log("Starting Gmail scan…");

  try {
    // 1. Scan Gmail
    const scanResult = await callTool("scan_gmail_subscriptions", { days_back: 90, max_results: 100 });
    log(`Gmail scan complete — ${scanResult.count ?? 0} emails found.`, "ok");

    // 2. Classify (deterministic, no LLM)
    setStatus("busy", "Classifying emails…");
    log(`Classifying ${scanResult.count || 0} emails...`);
    const classified = await callTool("classify_emails", {
      emails: scanResult.emails || []
    });
    log(`Classified ${classified.subscriptions?.length || 0} active subscriptions.`, "ok");

    lastSubscriptions = classified.subscriptions || [];

    // 3. Calculate bleed (deterministic math)
    setStatus("busy", "Calculating bleed…");
    log("Calculating financial bleed…");
    const bleed = await callTool("calculate_bleed", {
      subscriptions: classified.subscriptions || []
    });
    log(`Annual bleed: ${fmt(bleed.annual_bleed, bleed.currency)} across ${bleed.total_subscriptions} subscriptions.`, "ok");

    // 4. Render UI
    renderStats(bleed);
    renderDrains(bleed.top_3_drains, bleed.currency);
    renderTable(bleed.per_vendor, bleed.currency);

    // 5. Persist
    try {
      await callTool("save_subscriptions", {
        subscriptions: classified.subscriptions || [],
        annual_bleed: bleed.annual_bleed || 0
      });
      log("Subscription history saved.", "ok");
    } catch (e) {
      log(`Save skipped: ${e.message}`, "info");
    }

    setStatus("ready", "Scan complete");
    $("hero").style.display = "none";

  } catch (e) {
    log(`Error: ${e.message}`, "err");
    setStatus("error", "Error — see log");
  } finally {
    setScanBtnState(false);
  }
}

async function createAlerts() {
  const btn = $("alerts-btn");
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span> Creating…`;
  log("Creating Google Calendar alerts…");

  try {
    const result = await callTool("create_bulk_alerts", { subscriptions: lastSubscriptions });
    log(`Calendar alerts: ${result.created ?? 0} created, ${result.failed ?? 0} failed.`,
        (result.failed ?? 0) === 0 ? "ok" : "info");
    btn.textContent = `✅ ${result.created ?? 0} Alerts Created`;
  } catch (e) {
    log(`Calendar error: ${e.message}`, "err");
    btn.disabled = false;
    btn.textContent = "📅 Create Calendar Alerts";
  }
}

// ─── Bootstrap ───────────────────────────────────────────────────────────────

async function main() {
  try {
    anna = await AnnaAppRuntime.connect();
    await anna.window.set_title({ title: "Recoup — Subscription Killer" });
    setStatus("ready", "Connected to Anna");
    log("Anna runtime connected.", "ok");
  } catch (_) {
    setStatus("ready", "Standalone preview");
    log("Running in standalone preview (no Anna host). Demo data will be used.", "info");
  }

  $("scan-btn").disabled = false;
  $("scan-btn").addEventListener("click", runScan);
  $("alerts-btn").addEventListener("click", createAlerts);
}

main();
