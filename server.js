// server.js — standalone local server, proxies to recoup_plugin.py over stdio
const http = require("http");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");

const PLUGIN_PATH = path.join(__dirname, "executas", "recoup", "recoup_plugin.py");
const PORT = process.env.PORT || 3000;

let plugin = null;
let reqId = 1;
const pending = new Map();

function startPlugin() {
  plugin = spawn("python", [PLUGIN_PATH]);
  let buffer = "";

  plugin.stdout.on("data", (chunk) => {
    buffer += chunk.toString();
    let lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const msg = JSON.parse(line);
        const resolver = pending.get(msg.id);
        if (resolver) {
          pending.delete(msg.id);
          resolver(msg);
        }
      } catch {}
    }
  });

  plugin.stderr.on("data", (d) => console.error("[plugin]", d.toString()));
  plugin.on("exit", (code) => {
    console.error(`Plugin exited with code ${code}, restarting...`);
    setTimeout(startPlugin, 500);
  });
}

function callPlugin(method, params) {
  return new Promise((resolve) => {
    const id = reqId++;
    pending.set(id, resolve);
    plugin.stdin.write(JSON.stringify({ jsonrpc: "2.0", id, method, params }) + "\n");
  });
}

// Simple credential store — set GMAIL_ACCESS_TOKEN as an env var for local real testing
function getCredentials() {
  const creds = {};
  if (process.env.GMAIL_ACCESS_TOKEN) creds.GMAIL_ACCESS_TOKEN = process.env.GMAIL_ACCESS_TOKEN;
  if (process.env.GOOGLE_CALENDAR_TOKEN) creds.GOOGLE_CALENDAR_TOKEN = process.env.GOOGLE_CALENDAR_TOKEN;
  return creds;
}

const server = http.createServer(async (req, res) => {
  if (req.url === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ status: "ok" }));
  }

  if (req.url === "/api/invoke" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", async () => {
      const { method, args } = JSON.parse(body);
      const result = await callPlugin("invoke", {
        tool: method,
        arguments: args,
        context: { credentials: getCredentials() }
      });
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(result.result || result.error || {}));
    });
    return;
  }

  if (req.url.startsWith("/api/storage/get")) {
    const key = new URL(req.url, "http://x").searchParams.get("key");
    const file = path.join(require("os").homedir(), ".anna", "recoup", "kv.json");
    let store = {};
    if (fs.existsSync(file)) store = JSON.parse(fs.readFileSync(file, "utf-8"));
    res.writeHead(200, { "Content-Type": "application/json" });
    return res.end(JSON.stringify({ value: store[key] || null }));
  }

  if (req.url === "/api/storage/set" && req.method === "POST") {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      const { key, value } = JSON.parse(body);
      const dir = path.join(require("os").homedir(), ".anna", "recoup");
      const file = path.join(dir, "kv.json");
      fs.mkdirSync(dir, { recursive: true });
      let store = {};
      if (fs.existsSync(file)) store = JSON.parse(fs.readFileSync(file, "utf-8"));
      store[key] = value;
      fs.writeFileSync(file, JSON.stringify(store));
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ ok: true }));
    });
    return;
  }

  // Static file serving for bundle/
  let filePath = path.join(__dirname, "bundle", req.url === "/" ? "index.html" : req.url);
  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      return res.end("Not found");
    }
    const ext = path.extname(filePath);
    const types = { ".html": "text/html", ".js": "application/javascript", ".css": "text/css", ".png": "image/png" };
    res.writeHead(200, { "Content-Type": types[ext] || "text/plain" });
    res.end(data);
  });
});

startPlugin();
server.listen(PORT, () => console.log(`Recoup running at http://localhost:${PORT}`));
