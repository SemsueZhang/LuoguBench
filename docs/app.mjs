import config from "./config.mjs";
import { parseAnswerFile, summarize, sha256 } from "./scoring.mjs";
import { referenceLevels } from "./reference.mjs";

const form = document.querySelector(".submit-card form");
const input = form.querySelector('input[type="file"]');
const zone = form.querySelector(".drop-zone");
const submit = form.querySelector(".submit-button");
const initialIcon = zone.querySelector(".upload-icon").innerHTML;
const resultCard = document.querySelector(".result-card");
let currentText = "", currentName = "", currentReport = null;

function save(text, filename, type = "application/json") {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a"); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function showError(message) {
  form.querySelector(".error-message")?.remove();
  const box = document.createElement("div"); box.className = "error-message"; box.role = "alert";
  const text = document.createElement("span"); text.textContent = message;
  const close = document.createElement("button"); close.type = "button"; close.textContent = "×";
  close.setAttribute("aria-label", "关闭提示"); close.onclick = () => box.remove();
  box.append(text, close); submit.before(box);
}
function resetReport() {
  currentReport = null; resultCard.classList.remove("complete");
  resultCard.querySelector(".report-state").textContent = "等待提交";
  resultCard.querySelector(".report-state").classList.remove("ready");
  resultCard.querySelector(".primary-metric>strong").textContent = "—";
  resultCard.querySelector(".primary-metric p").textContent = "衡量难度排序与参考标签的一致性。";
  for (const [i, node] of [...resultCard.querySelectorAll(".metrics-grid strong")].entries()) {
    const small = document.createElement("small"); small.textContent = i === 2 ? "/ 87" : "";
    node.replaceChildren(document.createTextNode("—"), small);
  }
  resultCard.querySelectorAll(".runtime-output").forEach((el) => el.remove());
  resultCard.querySelector(".empty-note").hidden = false;
}
async function readFile(file) {
  form.querySelector(".error-message")?.remove(); resetReport(); currentText = ""; currentName = ""; submit.disabled = true;
  zone.classList.remove("has-file");
  zone.querySelector("strong").textContent = "把答案文件拖到这里";
  zone.querySelector(".upload-icon").innerHTML = initialIcon;
  zone.querySelector("button").textContent = "或点击选择文件";
  zone.querySelector(":scope>span").textContent = "answers.jsonl · 最大 4 MB";
  try {
    if (!file.name.toLowerCase().endsWith(".jsonl")) throw new Error("请上传 .jsonl 文件，每行一题，包含 id 和 level。");
    if (file.size > 4 * 1024 * 1024) throw new Error("答案文件不能超过 4 MB。");
    const text = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
    const rows = parseAnswerFile(text, config.ids);
    currentText = text; currentName = file.name; submit.disabled = false;
    zone.classList.add("has-file"); zone.querySelector("strong").textContent = file.name;
    zone.querySelector("button").textContent = "更换文件";
    zone.querySelector(":scope>span").textContent = `已校验 ${rows.length} / 87 题`;
    zone.querySelector(".upload-icon").innerHTML = '<svg width="25" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="m5 12 4 4L19 6"/></svg>';
  } catch (error) { showError(error instanceof Error ? error.message : "无法读取文件，请使用 UTF-8 编码。"); }
}
zone.querySelector("button").addEventListener("click", () => input.click());
input.addEventListener("change", () => { if (input.files?.[0]) void readFile(input.files[0]); input.value = ""; });
zone.addEventListener("dragover", (event) => { event.preventDefault(); zone.classList.add("dragging"); });
zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
zone.addEventListener("drop", (event) => { event.preventDefault(); zone.classList.remove("dragging"); if (event.dataTransfer.files[0]) void readFile(event.dataTransfer.files[0]); });
for (const button of document.querySelectorAll(".format-example button,.template-link")) button.addEventListener("click", () => {
  save(config.ids.map((id) => JSON.stringify({ id, level: null })).join("\n") + "\n", "answers-template.jsonl", "application/x-ndjson;charset=utf-8");
});

function displayReport(report) {
  const m = report.metrics, fmt = (value, digits = 4) => value === null ? "—" : value.toFixed(digits);
  const percent = (value) => `${(value * 100).toFixed(1)}%`;
  resultCard.classList.add("complete");
  const state = resultCard.querySelector(".report-state"); state.classList.add("ready"); state.textContent = "✓ 已完成";
  resultCard.querySelector(".primary-metric>strong").textContent = fmt(m.spearman_rho);
  resultCard.querySelector(".primary-metric p").textContent = m.spearman_rho === null ? "预测为常数时，相关系数没有定义。" : "衡量难度排序与参考标签的一致性。";
  const values = [percent(m.accuracy), fmt(m.mae, 3), String(m.n), percent(m.within_one_level)];
  [...resultCard.querySelectorAll(".metrics-grid strong")].forEach((node, i) => {
    const small = document.createElement("small"); small.textContent = i === 1 ? "档" : i === 2 ? "/ 87" : "";
    node.replaceChildren(document.createTextNode(values[i]), small);
  });
  resultCard.querySelector(".empty-note").hidden = true;
  const extra = document.createElement("div"); extra.className = "runtime-output";
  const details = document.createElement("details"); details.className = "report-details";
  const summary = document.createElement("summary"); summary.textContent = "其他指标"; details.append(summary);
  const list = document.createElement("dl"); list.className = "extra-metrics";
  for (const [title, value] of [["Kendall τ-b", fmt(m.kendall_tau_b)], ["加权 Kappa", fmt(m.quadratic_weighted_kappa)], ["命中题数", `${m.exact_matches} / 87`]]) {
    const row = document.createElement("div"), term = document.createElement("dt"), desc = document.createElement("dd");
    term.textContent = title; desc.textContent = value; row.append(term, desc); list.append(row);
  }
  details.append(list);
  const button = document.createElement("button"); button.type = "button"; button.className = "report-download"; button.textContent = "↓ 下载 JSON 报告";
  button.onclick = () => save(JSON.stringify(report, null, 2), `luogubench-${report.result_id.slice(0, 8)}.json`);
  extra.append(details, button); resultCard.append(extra);
}
form.addEventListener("submit", async (event) => {
  event.preventDefault(); form.querySelector(".error-message")?.remove();
  if (!currentText) { showError("请先选择一份包含全部 87 题答案的 JSONL 文件。"); return; }
  submit.disabled = true;
  const sourceText = currentText, sourceName = currentName;
  try {
    const rows = parseAnswerFile(sourceText, config.ids), actual = referenceLevels();
    if (actual.length !== config.ids.length || actual.some((v) => !Number.isInteger(v) || v < 1 || v > 8)) throw new Error("评分参考数据不完整，请刷新页面或联系维护者。");
    const report = {
      report_version: 1, result_id: crypto.randomUUID(), graded_at_utc: new Date().toISOString(),
      dataset_id: config.dataset_id, dataset_version: config.dataset_version, bundle_fingerprint: config.bundle_fingerprint,
      submission_name: sourceName, protocol_id: "web-file-v1", execution: "browser-local", model_identity_independently_verified: false,
      required_generation_protocol_id: config.protocol_id, required_prompt_set_sha256: config.prompt_set_sha256,
      generation_protocol_independently_verified: false,
      prediction_sha256: await sha256(sourceText), rationale_quality_scored: false, bootstrap_computed: false,
      metrics: summarize(actual, rows.map((r) => r.level)),
    };
    if (currentText !== sourceText) return;
    resetReport(); currentReport = report; displayReport(report);
    if (innerWidth < 800) document.querySelector("#result").scrollIntoView({ behavior: "smooth" });
  } catch (error) { showError(error instanceof Error ? error.message : "评分失败，请重试。"); }
  finally { submit.disabled = false; }
});
