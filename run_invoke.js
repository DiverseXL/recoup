#!/usr/bin/env node
/**
 * run_invoke.js — Direct JSON-RPC harness for recoup_plugin.py.
 *
 * Uses async spawn (not spawnSync) so stdin stays open until the plugin
 * sends back the invoke response — critical for tools like scan_gmail_subscriptions
 * that make outbound HTTP calls before replying.
 *
 * Usage:
 *   node run_invoke.js <tool_name> [args_json_file]
 *
 * Credentials (set in PowerShell before calling):
 *   $env:GMAIL_ACCESS_TOKEN    = "ya29...."
 *   $env:GOOGLE_CALENDAR_TOKEN = "ya29...."   # optional
 *
 * Examples:
 *   node run_invoke.js ping
 *   node run_invoke.js scan_gmail_subscriptions empty.json
 *   node run_invoke.js classify_emails test_emails.json
 *   node run_invoke.js calculate_bleed args.json
 */
"use strict";

const { spawn }   = require("child_process");
const fs          = require("fs");
const path        = require("path");
const readline    = require("readline");

// ── Args ─────────────────────────────────────────────────────────────────────
const tool     = process.argv[2];
const argsFile = process.argv[3] || null;

if (!tool) {
  console.error("Usage: node run_invoke.js <tool_name> [args_json_file]");
  process.exit(1);
}

let toolArgs = {};
if (argsFile) {
  try {
    toolArgs = JSON.parse(fs.readFileSync(path.resolve(argsFile), "utf8").trim());
  } catch (e) {
    console.error(`Failed to parse ${argsFile}:`, e.message);
    process.exit(1);
  }
}

// ── Credentials from env ──────────────────────────────────────────────────────
const credentials = {};
if (process.env.GMAIL_ACCESS_TOKEN)    credentials.GMAIL_ACCESS_TOKEN    = process.env.GMAIL_ACCESS_TOKEN;
if (process.env.GOOGLE_CALENDAR_TOKEN) credentials.GOOGLE_CALENDAR_TOKEN = process.env.GOOGLE_CALENDAR_TOKEN;

const credKeys = Object.keys(credentials);
process.stderr.write(`[run_invoke] tool=${tool}  credentials=${credKeys.length ? credKeys.join(", ") : "(none)"}\n`);

// ── Build JSON-RPC payload ────────────────────────────────────────────────────
const initMsg   = JSON.stringify({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2.0" } });
const invokeMsg = JSON.stringify({
  jsonrpc: "2.0",
  id: 2,
  method: "invoke",
  params: { tool, arguments: toolArgs, context: { credentials } },
});

// ── Spawn the plugin (async — stdin stays open until we get id:2 back) ────────
const pluginPath = path.join(process.cwd(), "recoup_plugin.py");
if (!fs.existsSync(pluginPath)) {
  console.error("recoup_plugin.py not found in CWD:", process.cwd());
  process.exit(1);
}

const python = process.platform === "win32" ? "python" : "python3";

const child = spawn(python, [pluginPath], {
  stdio: ["pipe", "pipe", "inherit"],   // stdin=pipe, stdout=pipe, stderr→terminal
  env:   process.env,
  cwd:   process.cwd(),
});

child.on("error", (err) => {
  console.error("Failed to spawn plugin:", err.message);
  process.exit(1);
});

// ── Read stdout line-by-line, look for id:2 response ─────────────────────────
const rl = readline.createInterface({ input: child.stdout, crlfDelay: Infinity });

rl.on("line", (line) => {
  line = line.trim();
  if (!line) return;
  let msg;
  try { msg = JSON.parse(line); } catch (_) { return; }

  if (msg.id === 2) {
    if (msg.result !== undefined) {
      console.log(JSON.stringify(msg.result, null, 2));
    } else if (msg.error) {
      console.error("RPC error:", JSON.stringify(msg.error, null, 2));
    }
    // Signal EOF to plugin → triggers its finally/shutdown block
    child.stdin.end();
  }
});

// ── Send the two messages, leave stdin open ───────────────────────────────────
child.stdin.write(initMsg   + "\n");
child.stdin.write(invokeMsg + "\n");
// Do NOT close stdin here — the plugin shuts down when it sees EOF,
// which we send above only after receiving the response.

// ── Timeout (90s — generous for Gmail API) ────────────────────────────────────
const timeout = setTimeout(() => {
  console.error("[run_invoke] Timeout: no response after 90s");
  child.stdin.end();
  child.kill();
  process.exit(1);
}, 300_000);

child.on("close", () => {
  clearTimeout(timeout);
  process.exit(0);
});
