// Runs Kin's real Today prompt (production model, real sanitizer) over every case
// and writes a grading sheet. Mono is imported read-only.
// Usage, from whetstone/:
//   LANGFUSE_TRACING_ENABLED=false ~/Developer/mono/node_modules/.bin/tsx \
//     --env-file=$HOME/Developer/mono/apps/backend/.env spike/generate.ts [round]
import { writeFileSync, mkdirSync } from "node:fs";
import { resolveFixture } from "../../mono/apps/backend/src/eval/resolveFixture";
import { buildInsightPrompt } from "../../mono/apps/backend/src/domain/ai/prompts/insightPrompt";
import { sanitizeInsightCard } from "../../mono/apps/backend/src/domain/ai/sanitizeInsight";
import { createLLMProvider } from "../../mono/apps/backend/src/infra/llm/createLLMProvider";
import { InsightOutputSchema } from "../../mono/packages/contracts/src";
import { cases, type Case } from "./cases";

const PINNED_NOW = "2026-10-21";
const round = process.argv[2] ?? "round1";
const llm = createLLMProvider("anthropic");
if (llm.modelFor?.("default") !== "claude-opus-5") throw new Error(`expected claude-opus-5, got ${llm.modelFor?.("default")}`);

function messagesFor(c: Case) {
  const r = resolveFixture(
    { id: c.id, suite: "capability", origin: "whetstone", pinnedNow: PINNED_NOW, target: "today_insight", input: c },
    PINNED_NOW,
  );
  if (r.target === "baseline_line") throw new Error("unreachable");
  return buildInsightPrompt({
    ...r,
    mode: "TODAY",
    seasonalGoal: c.seasonalGoal ?? null,
    competitionFormat: c.competitionFormat ?? null,
    recentAngles: c.recentAngles,
  });
}

async function run(c: Case) {
  const messages = messagesFor(c);
  try {
    const raw = await llm.structured(messages, InsightOutputSchema);
    return { id: c.id, note: c.note, userPrompt: messages[1].content, raw, shipped: sanitizeInsightCard(raw) };
  } catch (error) {
    return { id: c.id, note: c.note, userPrompt: messages[1].content, error: String(error) };
  }
}

void main();

async function main() {
// ponytail: fixed batches of 5, a pool only if runs get slow
const results = [];
for (let i = 0; i < cases.length; i += 5) {
  results.push(...(await Promise.all(cases.slice(i, i + 5).map(run))));
  console.log(`${results.length}/${cases.length}`);
}

mkdirSync("spike/runs", { recursive: true });
writeFileSync(`spike/runs/${round}.json`, JSON.stringify(results, null, 2));

// The input up to the framework section is what a grader needs; the rest is static instructions.
const inputOf = (p: string) => p.split("\nRelevant principles")[0].trim();
const sheet = results.map((r, i) => {
  const out = "shipped" in r && r.shipped
    ? `**${r.shipped.title}**\n\n_${r.shipped.summary}_\n\n${r.shipped.meaning}\n\n**Try:** ${r.shipped.try}\n\n\`${(r.shipped.tags ?? []).join("` `")}\``
    : `FAILED: ${"error" in r ? r.error : "no output"}`;
  return `## ${i + 1}. ${r.id}\n\n> ${r.note}\n\n<details><summary>Input</summary>\n\n\`\`\`\n${inputOf(r.userPrompt)}\n\`\`\`\n</details>\n\n${out}\n\ngrade: \nreason: \n`;
});
writeFileSync(
  `spike/${round}.md`,
  `# ${round}: grade each output\n\nWrite \`good\` or \`bad\` after grade:, and for bad, one line after reason: saying what's wrong.\n\n${sheet.join("\n---\n\n")}`,
);
console.log(`wrote spike/${round}.md`);
}
