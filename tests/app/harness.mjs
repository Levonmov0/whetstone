// The swipe app in jsdom, its server faked: `routes(path, grader, options)` answers each request.
import { readFileSync } from "node:fs";
import { after } from "node:test";
import { JSDOM } from "jsdom";

const html = readFileSync(new URL("../../src/whetstone/entry/static/app.html", import.meta.url), "utf8");

export const tick = (ms = 20) => new Promise((resolve) => setTimeout(resolve, ms));

// A test that fails before its close() would leave the app's poll running and the run hanging: close every window at the end.
const open = new Set();
after(() => { for (const window of open) window.close(); });

export async function boot(routes, grader = "A") {
  const dom = new JSDOM(html, {
    url: "http://phone/#t=token", runScripts: "dangerously", pretendToBeVisual: true,
    beforeParse(window) {
      window.localStorage.setItem("ws-grader", grader);
      window.fetch = async (path, options) => {
        const answer = await routes(path, decodeURIComponent(options.headers["X-Grader"]), options);
        if (answer.delay) await tick(answer.delay);
        return { ok: answer.status < 300, status: answer.status, json: async () => answer.body };
      };
      window.HTMLElement.prototype.animate = () => ({ finished: Promise.resolve(), cancel() {} });
      window.matchMedia = () => ({ matches: true, addEventListener() {} });
    },
  });
  open.add(dom.window);
  await tick(60);
  return dom.window;
}

export function button(window, text) {
  const found = [...window.document.querySelectorAll("button")].find((b) => (text instanceof RegExp ? text.test(b.textContent) : b.textContent.trim() === text));
  if (!found) throw new Error(`no button ${text}`);
  return found;
}

export async function rename(window, name) {
  window.document.getElementById("rename").click();
  await tick();
  window.document.getElementById("name").value = name;
  window.document.querySelector("form").dispatchEvent(new window.Event("submit", { cancelable: true }));
  await tick(60);
}

export const ask = (id) => ({ id, card_id: `d:${id}`, note: `note ${id}`, excerpt: "excerpt", reasons: ["tone"], why: "why" });
export const sure = (id, undone = false) => ({ id, card_id: `d:${id}`, note: `note ${id}`, reasons: ["tone"], undone });
export const card = (id) => ({ card_id: `d:${id}`, output: "Your HRV is low.", input: {}, caught_by: [], judges: [] });
export const matches = (items, sureItems = [], reasons = ["tone", "jargon"]) => ({ status: 200, body: { items, reasons, sure: sureItems } });
