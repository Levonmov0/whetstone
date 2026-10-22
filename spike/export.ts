// Freezes the production Today prompt per case into JSON for the Python GEPA run:
// system message, the user message minus its "YOUR JOB TODAY" block, that block
// (the seed GEPA rewrites), and the exact tool schema production sends.
import { writeFileSync, mkdirSync } from "node:fs";
import { z } from "../../mono/node_modules/zod";
import { resolveFixture } from "../../mono/apps/backend/src/eval/resolveFixture";
import { buildInsightPrompt } from "../../mono/apps/backend/src/domain/ai/prompts/insightPrompt";
import { InsightOutputSchema } from "../../mono/packages/contracts/src";
import { cases } from "./cases";

const PINNED_NOW = "2026-10-21";
const MARKER = "\n=== YOUR JOB TODAY ===";

let seed: string | undefined;
const parts = cases.map((c) => {
  const r = resolveFixture(
    { id: c.id, suite: "capability", origin: "whetstone", pinnedNow: PINNED_NOW, target: "today_insight", input: c },
    PINNED_NOW,
  );
  if (r.target === "baseline_line") throw new Error("unreachable");
  const [system, user] = buildInsightPrompt({
    ...r,
    mode: "TODAY",
    seasonalGoal: c.seasonalGoal ?? null,
    competitionFormat: c.competitionFormat ?? null,
    recentAngles: c.recentAngles,
  });
  const at = user.content.indexOf(MARKER);
  if (at < 0) throw new Error(`${c.id}: job block not found`);
  const job = user.content.slice(at);
  if (seed !== undefined && job !== seed) throw new Error(`${c.id}: job block differs between cases`);
  seed = job;
  return { id: c.id, hasDevice: (c.healthFacts ?? []).length > 0, system: system.content, userPrefix: user.content.slice(0, at) };
});

// Same call as AnthropicProvider.buildToolDefinition: the schema is an object, so no wrapper.
const inputSchema = z.toJSONSchema(InsightOutputSchema, { target: "draft-7" });
mkdirSync("spike/runs", { recursive: true });
writeFileSync("spike/runs/prompt_parts.json", JSON.stringify({ seedJob: seed, inputSchema, cases: parts }, null, 2));
console.log(`exported ${parts.length} cases, seed block ${seed!.length} chars`);
