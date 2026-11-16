"""Check that downloadable requests and actual adapter inputs cannot drift apart."""
import json
from pathlib import Path
import tempfile
import unittest

from luogubench.bundle import export_prompts, file_digest, load_bundle, prompt_digest
from luogubench.core import read_jsonl, sha
from luogubench.prompt import RUBRIC, render_prompt
from luogubench.runner import run_adapter

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "benchmark").exists():
    ROOT = ROOT / "publish/LuoguBench"
FROZEN_PROMPT_SET = "8975e33c9f6957e00d1c17bac6f25c68590ffd5cee056be5bb71ab38ec2b247a"


class PublicPromptContract(unittest.TestCase):
    def test_exported_artifacts_reproduce_the_frozen_input_contract(self):
        bundle = load_bundle(ROOT / "benchmark")
        self.assertEqual(bundle["rubric"].rstrip(), RUBRIC)
        self.assertEqual(prompt_digest(bundle), FROZEN_PROMPT_SET)
        self.assertFalse((ROOT / "prompts/requests.jsonl").exists())
        self.assertFalse((ROOT / "docs/agent-run.md").exists())
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "prompts"
            manifest = export_prompts(ROOT / "benchmark", out)
            self.assertEqual(manifest["prompt_set_sha256"], FROZEN_PROMPT_SET)
            for name in ("prompt.txt", "requests.jsonl", "manifest.json"):
                self.assertEqual((out / name).read_bytes(), (ROOT / "docs" / ("prompt-manifest.json" if name == "manifest.json" else name)).read_bytes())
            self.assertEqual(file_digest(out / "requests.jsonl"), manifest["requests_file_sha256"])
            rows = read_jsonl(out / "requests.jsonl")
            downloaded_digest = sha(json.dumps([
                {"id": r["id"], "sha256": sha(r["messages"][0]["content"])} for r in rows
            ], ensure_ascii=False, sort_keys=True))
            self.assertEqual(downloaded_digest, FROZEN_PROMPT_SET)
            self.assertEqual([r["id"] for r in rows], bundle["ids"])
            self.assertTrue(all(r["protocol_id"] == "isolated-text-v2" for r in rows))
            self.assertTrue(all(len(r["messages"]) == 1 and r["messages"][0]["role"] == "user" for r in rows))
            for row, item in zip(rows, bundle["items"]):
                self.assertEqual(row["messages"][0]["content"], render_prompt(item))
            self.assertEqual((ROOT / "docs/prompt.txt").read_bytes(), (out / "prompt.txt").read_bytes())
            self.assertEqual((ROOT / "docs/requests.jsonl").read_bytes(), (out / "requests.jsonl").read_bytes())
            with self.assertRaisesRegex(ValueError, "must be empty"):
                export_prompts(ROOT / "benchmark", out)

    def test_adapter_receives_the_same_message_as_the_public_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            captured = tmp / "request.json"
            adapter = tmp / "offline_adapter.py"
            adapter.write_text(
                "import json,sys\nfrom pathlib import Path\n"
                "r=json.load(sys.stdin)\n"
                f"Path({str(captured)!r}).write_text(json.dumps(r,ensure_ascii=False),encoding='utf-8')\n"
                "print(json.dumps({'prediction':{'id':r['id'],'level':1,'label':'入门','reason':'离线输入一致性检查'},'demo':True},ensure_ascii=False))\n",
                encoding="utf-8",
            )
            result = run_adapter(ROOT / "benchmark", adapter, tmp / "run", "offline-demo", limit=1)
            self.assertEqual(result["valid_predictions"], 1)
            self.assertTrue(result["is_demo"])
            request = json.loads(captured.read_text(encoding="utf-8"))
            published = read_jsonl(ROOT / "docs/requests.jsonl")[0]
            for key in ("id", "protocol_id", "messages", "response_schema"):
                self.assertEqual(request[key], published[key])


if __name__ == "__main__":
    unittest.main()
