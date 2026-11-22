import assert from "node:assert/strict";
import { test } from "node:test";
import { ask, boot, button, card, matches, rename, sure, tick } from "./harness.mjs";

test("a reply for the grader before Not you? never reaches the next one", async () => {
  let slow = false;
  const w = await boot((path, grader) => path === "/api/cards" ? { status: 200, body: { cards: [card("1")], reasons: [] } }
    : { ...matches([ask(`m_${grader}`)]), delay: grader === "A" && slow ? 200 : 0 });
  slow = true;
  w.eval("loadMatches()");
  await rename(w, "B");
  await tick(300);
  assert.deepEqual(w.eval("matches.map((m) => m.id)"), ["m_B"]);
  w.close();
});

test("Later is the grader's own: the next one's deck end still offers Check them", async () => {
  const w = await boot((path, grader) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } } : matches([ask(`m_${grader}`)]));
  button(w, "Later").click();
  await tick();
  await rename(w, "B");
  assert.ok(button(w, "Check them"));
  w.close();
});

test("Undo after a refresh shows Redo, as stored", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } }
    : options?.method === "POST" ? { status: 200, body: {} } : matches([], [sure("m_1")]));
  w.eval("openMatching()");
  await tick();
  await w.eval("loadMatches()");
  button(w, "Undo").click();
  await tick(60);
  assert.deepEqual([...w.document.querySelectorAll(".sure-row button")].map((b) => b.textContent), ["Redo"]);
  w.close();
});

test("a 401 from the Different chip sheet closes it over the token message", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } }
    : options?.method === "POST" ? { status: 401, body: {} } : matches([ask("m_1")]));
  w.eval("openMatching()");
  await tick();
  button(w, /Different/).click();
  await tick();
  w.document.querySelector(".sheet .chip").click();
  w.document.querySelector(".sheet .count").click();
  await tick(60);
  assert.equal(w.document.querySelector("main h1").textContent, "Scan the QR code again");
  assert.equal(w.document.querySelector(".sheet-backdrop"), null);
  w.close();
});

test("a 401 from the Why is it bad? sheet closes it over the token message", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [card("1")], reasons: ["tone"] } }
    : options?.method === "POST" ? { status: 401, body: {} } : matches([]));
  button(w, "✕ Bad").click();
  await tick();
  w.document.getElementById("note").value = "Says HRV";
  button(w, "Save as bad").click();
  await tick(60);
  assert.equal(w.document.querySelector("main h1").textContent, "Scan the QR code again");
  assert.equal(w.document.querySelector(".sheet-backdrop"), null);
  w.close();
});

test("an item another phone answered No says so, whatever this phone tapped", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } }
    : options?.method === "POST" ? { status: 200, body: { answer: "no" } } : matches([ask("m_1")]));
  w.eval("openMatching()");
  await tick();
  button(w, "Yes").click();
  await tick(60);
  assert.equal(w.document.getElementById("status").textContent, "Kept as an idea for a new check");
  assert.match(w.document.querySelector("main").textContent, /0 now count toward a check\. 1 kept as an idea/);
  w.close();
});

test("an item another phone answered with a different chip counts as that chip", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } }
    : options?.method === "POST" ? { status: 200, body: { answer: "different", reason: "jargon" } } : matches([ask("m_1")]));
  w.eval("openMatching()");
  await tick();
  button(w, "Yes").click();
  await tick(60);
  assert.equal(w.document.getElementById("status").textContent, "✓ Counts as jargon");
  w.close();
});
