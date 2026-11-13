"""Offline integration checks for parallel scheduling, checkpoints and resumption."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from luogubench.bundle import load_bundle
from luogubench.core import read_jsonl, sha
from luogubench.runner import run_adapter

ROOT = Path(__file__).resolve().parents[1]


class ParallelRunner(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ids = load_bundle(ROOT / "benchmark")["ids"]

    def adapter(self, root, mode):
        settings = {"root": str(root), "mode": mode, "first": self.ids[0], "second": self.ids[1]}
        path = root / "adapter.py"
        path.write_text("import json,sys,time\nfrom pathlib import Path\n" +
                        f"settings={settings!r}\n" + """
r=json.load(sys.stdin)
root=Path(settings['root'])
item_id=r['id']
(root/(item_id+'.started')).touch()
(root/(item_id+'.request.json')).write_text(json.dumps(r,ensure_ascii=False),encoding='utf-8')
def await_condition(test):
    deadline=time.monotonic()+10
    while not test():
        if time.monotonic()>deadline:
            raise RuntimeError('parallel peer or checkpoint did not arrive')
        time.sleep(.01)
if settings['mode']=='overlap':
    if item_id==settings['first']:
        # The first request cannot finish until another result has been checkpointed.
        await_condition(lambda: settings['second'] in (root/'run/predictions.jsonl').read_text(encoding='utf-8'))
        (root/'checkpoint-observed').touch()
    elif item_id==settings['second']:
        await_condition(lambda: (root/(settings['first']+'.started')).exists())
if settings['mode']=='fail-once' and item_id==settings['first']:
    marker=root/'failed-once'
    if not marker.exists():
        marker.touch()
        print('invalid JSON')
        sys.exit(0)
if settings['mode']=='timeout':
    time.sleep(2)
(root/(item_id+'.finished')).touch()
print(json.dumps({'prediction':{'id':item_id,'level':1,'label':'入门','reason':'离线并发测试'},'demo':True},ensure_ascii=False))
""", encoding="utf-8")
        return path

    def test_requests_overlap_and_out_of_order_results_keep_bundle_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.adapter(root, "overlap")
            progress = io.StringIO()
            with contextlib.redirect_stderr(progress):
                result = run_adapter(ROOT / "benchmark", adapter, root / "run", "offline-demo",
                                     jobs=2, limit=2, timeout=15, progress=True)
            self.assertEqual(result["valid_predictions"], 2)
            self.assertTrue(result["is_demo"])
            self.assertTrue((root / "checkpoint-observed").exists())
            self.assertEqual(len(list(root.glob("*.started"))), 2)
            self.assertIn(self.ids[1], progress.getvalue().splitlines()[0])
            rows = read_jsonl(root / "run/predictions.jsonl")
            self.assertEqual([r["id"] for r in rows], self.ids[:2])
            published = read_jsonl(ROOT / "prompts/requests.jsonl")
            for expected in published[:2]:
                actual = json.loads((root / f"{expected['id']}.request.json").read_text(encoding="utf-8"))
                self.assertEqual(actual["messages"], expected["messages"])
            config = json.loads((root / "run/run.json").read_text())
            self.assertEqual(config["attempts"], 2)
            self.assertEqual(config["last_jobs"], 2)
            self.assertEqual(config["predictions_sha256"], sha((root / "run/predictions.jsonl").read_text(encoding="utf-8")))

    def test_failure_is_isolated_and_resume_only_retries_missing_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.adapter(root, "fail-once")
            first = run_adapter(ROOT / "benchmark", adapter, root / "run", "offline-demo", jobs=2, limit=2)
            self.assertEqual(first["valid_predictions"], 1)
            self.assertEqual(first["failed_ids"], [self.ids[0]])
            preserved = root / f"run/responses/{self.ids[1]}.attempt-1.json"
            before = preserved.read_bytes()
            second = run_adapter(ROOT / "benchmark", adapter, root / "run", "offline-demo",
                                 jobs=1, limit=1, resume=True)
            self.assertEqual(second["valid_predictions"], 2)
            self.assertEqual(second["failed_ids"], [])
            self.assertEqual(preserved.read_bytes(), before)
            self.assertEqual(len(list((root / "run/responses").glob("*.json"))), 3)
            self.assertTrue((root / f"run/responses/{self.ids[0]}.attempt-2.json").is_file())
            config = json.loads((root / "run/run.json").read_text())
            self.assertEqual(config["attempts"], 3)
            self.assertEqual(config["last_jobs"], 1)
            self.assertEqual([r["id"] for r in read_jsonl(root / "run/predictions.jsonl")], self.ids[:2])

    def test_timeout_is_recorded_per_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.adapter(root, "timeout")
            result = run_adapter(ROOT / "benchmark", adapter, root / "run", "offline-demo",
                                 jobs=2, limit=2, timeout=.1)
            self.assertEqual(result["valid_predictions"], 0)
            self.assertEqual(set(result["failed_ids"]), set(self.ids[:2]))
            records = [json.loads(p.read_text()) for p in (root / "run/responses").glob("*.json")]
            self.assertEqual(len(records), 2)
            self.assertTrue(all("TimeoutExpired" in r["error"] for r in records))

    def test_interrupt_stops_dispatch_and_saves_in_flight_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adapter = self.adapter(root, "normal")
            with patch("luogubench.runner.wait", side_effect=KeyboardInterrupt):
                result = run_adapter(ROOT / "benchmark", adapter, root / "run", "offline-demo",
                                     jobs=2, limit=3)
            self.assertTrue(result["interrupted"])
            self.assertEqual(result["valid_predictions"], 2)
            self.assertEqual(len(list(root.glob("*.started"))), 2)
            config = json.loads((root / "run/run.json").read_text())
            self.assertTrue(config["last_call_interrupted"])
            self.assertEqual(config["attempts"], 2)

    def test_invalid_parallelism_is_rejected_before_writing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            for jobs in (0, -1, True, 1.5):
                with self.assertRaisesRegex(ValueError, "jobs must be"):
                    run_adapter(ROOT / "benchmark", ROOT / "adapters/demo_constant.py", out, "offline-demo", jobs=jobs)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
