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

test("A5: a match Claude makes after the last swipe opens the deck end by itself", async () => {
  let made = false;
  const w = await boot((path) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } } : matches(made ? [ask("m_1")] : []));
  assert.equal(w.document.querySelector("main h1").textContent, "All graded");
  made = true;
  await tick(2300);
  assert.ok(button(w, "Check them"));
  w.close();
});

test("the poll leaves an unchanged All graded alone: focus stays on Check for new cards", async () => {
  const w = await boot((path) => path === "/api/cards" ? { status: 200, body: { cards: [], reasons: [] } } : matches([]));
  button(w, "Check for new cards").focus();
  await tick(2300);
  assert.equal(w.document.activeElement?.textContent, "Check for new cards");
  w.close();
});

test("A6: a badge tap while a swipe saves keeps the matching screen open", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [card("1"), card("2")], reasons: [] } }
    : path === "/api/swipes" ? { status: 201, body: {}, delay: 150 } : matches([ask("m_1")]));
  button(w, "✓ Good").click();
  w.document.getElementById("badge").click();
  await tick(500);
  assert.equal(w.document.querySelector("main h1").textContent, "Is this what you meant?");
  w.document.getElementById("back").click();
  await tick();
  assert.equal(w.document.getElementById("progress").textContent, "2 of 2");
  w.close();
});

test("A7: an Undo in flight when Back is tapped never draws Nothing to check over the cards", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [card("1")], reasons: [] } }
    : options?.method === "POST" ? { status: 200, body: {}, delay: 150 } : matches([], [sure("m_1")]));
  w.document.getElementById("badge").click();
  await tick();
  button(w, "Undo").click();
  button(w, "Back to cards").click();
  await tick(300);
  assert.ok(w.document.querySelector("main .card"));
  assert.doesNotMatch(w.document.querySelector("main").textContent, /Nothing to check/);
  w.close();
});

test("A8: a Yes in flight when Back is tapped is saved and leaves the badge", async () => {
  const w = await boot((path, _grader, options) => path === "/api/cards" ? { status: 200, body: { cards: [card("1")], reasons: [] } }
    : options?.method === "POST" ? { status: 200, body: { answer: "yes" }, delay: 150 } : matches([ask("m_1")]));
  w.document.getElementById("badge").click();
  await tick();
  button(w, "Yes").click();
  w.document.getElementById("back").click();
  await tick(300);
  assert.ok(w.document.querySelector("main .card"));
  assert.equal(w.document.getElementById("badge").hidden, true);
  w.close();
});
