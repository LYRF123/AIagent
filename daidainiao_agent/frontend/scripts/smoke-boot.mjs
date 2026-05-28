import { readFileSync } from "fs";
import { fileURLToPath, pathToFileURL } from "url";

const html = readFileSync(new URL("../index.html", import.meta.url), "utf8");
const ids = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));

function makeEl(id) {
  const tag = id.includes("input") || id === "session-search" ? "input" : "div";
  const el = {
    id,
    tagName: tag.toUpperCase(),
    hidden: id === "settings-panel",
    classList: { _c: new Set(), add(v) { this._c.add(v); }, remove(v) { this._c.delete(v); }, toggle(v, on) { on ? this._c.add(v) : this._c.delete(v); }, contains(v) { return this._c.has(v); } },
    style: {},
    dataset: {},
    attributes: {},
    children: [],
    parentElement: null,
    addEventListener() {},
    removeEventListener() {},
    querySelector(sel) {
      const m = sel.match(/#([\w-]+)/);
      if (m && store[m[1]]) return store[m[1]];
      return null;
    },
    querySelectorAll() { return []; },
    appendChild(c) { this.children.push(c); return c; },
    insertAdjacentHTML() {},
    setAttribute(k, v) { this.attributes[k] = v; },
    getAttribute(k) { return this.attributes[k]; },
    focus() {},
    click() {},
    value: "",
    checked: true,
    textContent: "",
  };
  return el;
}

const store = {};
for (const id of ids) store[id] = makeEl(id);
store.sidebar = store.sidebar || makeEl("sidebar");
store["chat-messages"] = store["chat-messages"] || makeEl("chat-messages");
store["welcome-screen"] = store["welcome-screen"] || makeEl("welcome-screen");

const appShell = {
  classList: { _c: new Set(), add(v) { this._c.add(v); }, remove(v) { this._c.delete(v); }, toggle(v, on) { on ? this._c.add(v) : this._c.delete(v); }, contains(v) { return this._c.has(v); } },
};
store["sidebar-toggle"] = store["sidebar-toggle"] || makeEl("sidebar-toggle");

const document = {
  getElementById: (id) => store[id] || null,
  querySelector: (sel) => {
    if (sel === ".app-shell") return appShell;
    const m = sel.match(/#([\w-]+)/);
    if (m) return store[m[1]] || null;
    return null;
  },
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: () => makeEl("_tmp"),
  body: { appendChild() {} },
  documentElement: { setAttribute() {}, removeAttribute() {} },
};

globalThis.window = {
  localStorage: { getItem: () => null, setItem() {} },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  __DODO_CHAT_READY: false,
};
globalThis.document = document;
globalThis.localStorage = window.localStorage;
globalThis.Event = class Event { constructor(t, o) { this.type = t; this.bubbles = o?.bubbles; } };
globalThis.MutationObserver = class { observe() {} };
globalThis.fetch = async (url) => {
  const u = String(url);
  if (u.includes("/sessions")) return { ok: true, json: async () => ({ items: [] }) };
  if (u.includes("/status") || u.includes("/runtime")) return { ok: true, json: async () => ({ corpus: {}, model: {}, usage: {}, retrieval: {} }) };
  if (u.includes("/knowledge")) return { ok: true, json: async () => ({ items: [] }) };
  if (u.includes("/model")) return { ok: true, json: async () => ({ profiles: [] }) };
  return { ok: true, json: async () => ({}) };
};

try {
  const appPath = fileURLToPath(new URL("../app.js", import.meta.url));
  await import(pathToFileURL(appPath).href);
  console.log("BOOT_OK", window.__DODO_CHAT_READY === true);
} catch (error) {
  console.error("BOOT_FAIL", error.stack || error);
  process.exit(1);
}
