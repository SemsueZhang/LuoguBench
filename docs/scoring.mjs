export const LEVELS = ["入门", "普及-", "普及", "普及+/提高-", "提高", "提高+/省选-", "省选/NOI-", "NOI/NOI+/CTS"];
export const MAX_TEXT = 4 * 1024 * 1024;

export class SubmissionError extends Error {
  constructor(message) { super(message); this.name = "SubmissionError"; }
}
const fail = (message) => { throw new SubmissionError(message); };
const isObject = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const mean = (values) => values.reduce((a, b) => a + b, 0) / values.length;

export async function sha256(text) {
  const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(hash)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function parseAnswerFile(text, ids) {
  if (typeof text !== "string" || !text.trim()) fail("答案文件为空。");
  if (new TextEncoder().encode(text).length > MAX_TEXT) fail("答案文件不能超过 4 MB。");
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  if (lines.length !== ids.length) fail(`需要 ${ids.length} 行答案，当前有 ${lines.length} 行。请把所有题的答案放在同一个 JSONL 文件里。`);
  const expected = new Set(ids), found = new Map();
  for (const [index, line] of lines.entries()) {
    let row;
    try { row = JSON.parse(line); } catch { fail(`第 ${index + 1} 行不是有效 JSON，请检查双引号与逗号。`); }
    if (!isObject(row) || typeof row.id !== "string" || !expected.has(row.id)) fail(`第 ${index + 1} 行的 id 不属于当前题集，请使用答案模板中的 ID。`);
    if (found.has(row.id)) fail(`题目 ${row.id} 重复，请每题只保留一行。`);
    if (!Number.isInteger(row.level) || row.level < 1 || row.level > 8) fail(`第 ${index + 1} 行的 level 必须是 1–8 的整数，请替换模板中的 null。`);
    // Only the predicted ordinal is scored. Rationale and label are optional diagnostics.
    found.set(row.id, { id: row.id, level: row.level });
  }
  return ids.map((id) => found.get(id));
}

export function ranks(values) {
  const order = values.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value);
  const result = new Array(values.length);
  for (let i = 0; i < order.length;) {
    let j = i + 1;
    while (j < order.length && order[j].value === order[i].value) j++;
    for (let k = i; k < j; k++) result[order[k].index] = (i + 1 + j) / 2;
    i = j;
  }
  return result;
}

export function pearson(x, y) {
  if (x.length !== y.length || x.length < 2) return null;
  const mx = mean(x), my = mean(y);
  let numerator = 0, vx = 0, vy = 0;
  for (let i = 0; i < x.length; i++) {
    const a = x[i] - mx, b = y[i] - my;
    numerator += a * b; vx += a * a; vy += b * b;
  }
  return vx && vy ? Math.max(-1, Math.min(1, numerator / Math.sqrt(vx * vy))) : null;
}

export function summarize(actual, predicted) {
  const n = actual.length;
  if (!n || n !== predicted.length) throw new Error("Invalid scoring vectors");
  const errors = actual.map((a, i) => predicted[i] - a);
  let concordant = 0, discordant = 0, tx = 0, ty = 0;
  for (let i = 0; i < n; i++) for (let j = 0; j < i; j++) {
    const dx = actual[i] - actual[j], dy = predicted[i] - predicted[j];
    tx += Number(dx === 0); ty += Number(dy === 0);
    concordant += Number(dx * dy > 0); discordant += Number(dx * dy < 0);
  }
  const pairs = n * (n - 1) / 2, kd = Math.sqrt((pairs - tx) * (pairs - ty));
  const ha = Array(8).fill(0), hp = Array(8).fill(0);
  actual.forEach((a) => ha[a - 1]++); predicted.forEach((p) => hp[p - 1]++);
  let expected = 0;
  for (let a = 0; a < 8; a++) for (let p = 0; p < 8; p++) expected += (a - p) ** 2 * ha[a] * hp[p] / n;
  const recalls = ha.map((count, i) => count ? actual.reduce((sum, a, j) => sum + Number(a === i + 1 && predicted[j] === a), 0) / count : null).filter((v) => v !== null);
  return {
    n, coverage: 1, spearman_rho: pearson(ranks(actual), ranks(predicted)),
    kendall_tau_b: kd ? (concordant - discordant) / kd : null,
    pearson_r: pearson(actual, predicted),
    accuracy: errors.filter((e) => e === 0).length / n,
    within_one_level: errors.filter((e) => Math.abs(e) <= 1).length / n,
    mae: mean(errors.map(Math.abs)), rmse: Math.sqrt(mean(errors.map((e) => e * e))),
    mean_signed_error: mean(errors),
    quadratic_weighted_kappa: expected ? 1 - errors.reduce((s, e) => s + e * e, 0) / expected : null,
    macro_recall: mean(recalls), exact_matches: errors.filter((e) => e === 0).length,
    within_one_count: errors.filter((e) => Math.abs(e) <= 1).length,
  };
}

