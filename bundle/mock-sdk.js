// bundle/mock-sdk.js — local-only stand-in for the Anna SDK
window.anna = {
  tools: {
    invoke: async ({ tool_id, method, args }) => {
      const res = await fetch("/api/invoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tool_id, method, args })
      });
      return res.json();
    }
  },
  storage: {
    get: async (key) => {
      const res = await fetch(`/api/storage/get?key=${encodeURIComponent(key)}`);
      return res.json();
    },
    set: async (key, value) => {
      const res = await fetch("/api/storage/set", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key, value })
      });
      return res.json();
    }
  }
};
