import test from "node:test";
import assert from "node:assert/strict";
import { parseAnswerFile, ranks, summarize } from "../docs/scoring.mjs";
import { referenceLevels } from "../docs/reference.mjs";
import config from "../docs/config.mjs";

const ids = ["a", "b", "c", "d"];
const file = (levels) => levels.map((level, i) => JSON.stringify({ id: ids[i], level })).join("\n");

test("Spearman average ranks and Kendall ties match the Python conventions", () => {
  assert.deepEqual(ranks([1, 2, 2, 3]), [1, 2.5, 2.5, 4]);
  const result = summarize([1, 2, 2, 3], [1, 3, 2, 2]);
  assert.equal(result.spearman_rho, 0.5);
  assert.equal(result.kendall_tau_b, 0.4);
});
test("undefined and reverse correlations are handled explicitly", () => {
  assert.equal(summarize([1, 2, 3], [2, 2, 2]).spearman_rho, null);
  assert.equal(summarize([1, 2, 3], [3, 2, 1]).spearman_rho, -1);
  assert.ok(Math.abs(summarize([1, 2, 3], [1, 3, 2]).quadratic_weighted_kappa - 0.5) < 1e-12);
});
test("the one-file format accepts id and level, any row order, BOM and CRLF", () => {
  const text = '\ufeff' + file([1, 2, 3, 4]).split("\n").reverse().join("\r\n") + "\n";
  assert.deepEqual(parseAnswerFile(text, ids), ids.map((id, i) => ({ id, level: i + 1 })));
});
test("label and rationale are optional and do not change rating scores", () => {
  const text = ids.map((id, i) => JSON.stringify({ id, level: i + 1, label: "not scored", reason: "optional" })).join("\n");
  assert.deepEqual(parseAnswerFile(text, ids), parseAnswerFile(file([1, 2, 3, 4]), ids));
});
test("missing answers, duplicate IDs, foreign IDs and non-integer levels are rejected", () => {
  assert.throws(() => parseAnswerFile(file([1, 2]), ids));
  for (const value of [null, true, "5", 0, 9, 2.5]) assert.throws(() => parseAnswerFile(file([1, 2, 3, value]), ids));
  assert.throws(() => parseAnswerFile(file([1, 2, 3, 4]).replace('"d"', '"a"'), ids));
  assert.throws(() => parseAnswerFile(file([1, 2, 3, 4]).replace('"d"', '"other"'), ids));
});
test("JSON arrays and missing level keys do not silently change the specified format", () => {
  assert.throws(() => parseAnswerFile("[1,2,3,4]", ids));
  assert.throws(() => parseAnswerFile(file([1, 2, 3, 4]).replace('"level":4', '"answer":4'), ids));
});
test("browser reference data and anonymous ID inventory stay aligned", () => {
  const reference = referenceLevels();
  assert.equal(reference.length, 87);
  assert.equal(config.ids.length, 87);
  assert.equal(new Set(config.ids).size, 87);
  assert.ok(reference.every((v) => Number.isInteger(v) && v >= 1 && v <= 8));
  assert.equal(summarize(reference, reference).spearman_rho, 1);
});
