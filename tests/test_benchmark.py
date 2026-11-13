import json
import math
from pathlib import Path
import tempfile
import unittest

from luogubench.core import LEVELS, code_blocks, samples, sanitize, sha, strip_cpp_comments, write_jsonl
from luogubench.metrics import (bootstrap_spearman, kendall_tau_b, pearson,
                               quadratic_weighted_kappa, ranks, spearman)
from luogubench.score import score
from luogubench.cli import export
from luogubench.verify import compare_output, verify


class StatisticalConventions(unittest.TestCase):
    def test_ties_use_average_ranks(self):
        self.assertEqual(ranks([1, 2, 2, 3]), [1, 2.5, 2.5, 4])
        # Hand-calculated tied example: rank covariance 2.25 / variance 4.5.
        self.assertAlmostEqual(spearman([1, 2, 2, 3], [1, 3, 2, 2]), 0.5)
        # Three concordant pairs, one discordant, one tie in each variable.
        self.assertAlmostEqual(kendall_tau_b([1, 2, 2, 3], [1, 3, 2, 2]), 0.4)

    def test_perfect_reverse_and_degenerate(self):
        self.assertAlmostEqual(spearman([1, 2, 3], [3, 2, 1]), -1)
        self.assertAlmostEqual(kendall_tau_b([1, 2, 3], [3, 2, 1]), -1)
        self.assertIsNone(spearman([1, 2, 3], [2, 2, 2]))
        self.assertIsNone(pearson([1], [1]))
        self.assertIsNone(kendall_tau_b([1, 1], [2, 2]))

    def test_weighted_kappa_known_example(self):
        self.assertAlmostEqual(quadratic_weighted_kappa([1, 2, 3], [1, 3, 2]), 0.5)
        self.assertAlmostEqual(quadratic_weighted_kappa([1, 4, 8], [1, 4, 8]), 1)

    def test_bootstrap_reproducibility_and_undefined_replicates(self):
        first = bootstrap_spearman([1, 2, 3], [1, 2, 3], 50, 17)
        self.assertEqual(first, bootstrap_spearman([1, 2, 3], [1, 2, 3], 50, 17))
        self.assertEqual(first["percentile_95"], [1.0, 1.0])
        self.assertIsNone(bootstrap_spearman([1, 1], [2, 2], 10)["percentile_95"])


class StrictEvaluation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.labels = self.root / "labels.jsonl"
        self.pred = self.root / "pred.jsonl"
        write_jsonl(self.labels, [
            {"id": "a", "level": 1, "label": LEVELS[1], "problem_id": "P1", "bucket": "red"},
            {"id": "b", "level": 8, "label": LEVELS[8], "problem_id": "P2", "bucket": "black_easy"},
        ])

    def tearDown(self):
        self.tmp.cleanup()

    def p(self, item_id="a", level=1):
        return {"id": item_id, "level": level, "label": LEVELS[level], "reason": "关键观察及实现负担"}

    def test_missing_is_not_silently_dropped(self):
        write_jsonl(self.pred, [self.p()])
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            score(self.labels, self.pred, self.root / "out", bootstrap=0)
        result = score(self.labels, self.pred, self.root / "out", allow_partial=True, bootstrap=0)
        self.assertEqual(result["coverage"], 0.5)
        self.assertIsNone(result["spearman_rho"])

    def test_duplicate_unknown_and_invalid_fields(self):
        for rows in [[self.p(), self.p()], [self.p("unknown")], [{**self.p(), "level": True}],
                     [{**self.p(), "label": "旧体系标签"}], [{**self.p(), "reason": " "}]]:
            write_jsonl(self.pred, rows)
            with self.assertRaises(ValueError):
                score(self.labels, self.pred, self.root / "out", bootstrap=0)

    def test_alignment_is_by_id_and_black_is_one_level(self):
        write_jsonl(self.pred, [self.p("b", 8), self.p("a", 1)])
        result = score(self.labels, self.pred, self.root / "out", bootstrap=0)
        self.assertEqual(result["accuracy"], 1)
        self.assertEqual(result["spearman_rho"], 1)

    def test_export_rejects_truth_contamination(self):
        path = self.root / "inputs.jsonl"
        write_jsonl(path, [{"id": "a", "statement_md": "x", "solutions": [], "level": 1}])
        with self.assertRaisesRegex(ValueError, "label-free"):
            export(path, self.root / "blind", 1)

    def test_export_rejects_nested_truth_contamination(self):
        path = self.root / "nested.jsonl"
        std = {"language": "cpp17", "interface": "stdin_stdout", "code": "int main(){}"}
        solution = {"method_id": "method_1", "editorial_md": "推导", "std": std}
        for mutated in [{**solution, "label": "NOI/NOI+/CTS"}, {**solution, "std": {**std, "gold_level": 8}}]:
            write_jsonl(path, [{"id": "a", "statement_md": "x", "solutions": [mutated]}])
            with self.assertRaisesRegex(ValueError, "label-free"):
                export(path, self.root / "nested_blind", 1)

    def test_export_copies_only_referenced_images_and_rejects_duplicate_ids(self):
        source = self.root / "materials"
        (source / "assets").mkdir(parents=True)
        (source / "assets/Iexample.png").write_bytes(b"test image bytes")
        (source / "asset_provenance.json").write_text('{"gold_level": 8}')
        row = {"id": "safe", "statement_md": "![原文插图](assets/Iexample.png)", "solutions": [
            {"method_id": "method_1", "editorial_md": "思路", "std": {"language": "cpp17", "interface": "stdin_stdout", "code": "int main(){}"}}]}
        path = source / "inputs.jsonl"
        write_jsonl(path, [row])
        target = self.root / "image_blind"
        export(path, target, 1)
        self.assertEqual((target / "assets/Iexample.png").read_bytes(), b"test image bytes")
        self.assertFalse((target / "asset_provenance.json").exists())
        write_jsonl(path, [row, row])
        with self.assertRaisesRegex(ValueError, "unique IDs"):
            export(path, self.root / "duplicate_blind", 1)

    def test_truth_boolean_is_rejected_before_outputs(self):
        labels = [{"id": "a", "level": True, "label": LEVELS[1], "problem_id": "P1", "bucket": "red"}]
        write_jsonl(self.labels, labels)
        write_jsonl(self.pred, [self.p()])
        with self.assertRaisesRegex(ValueError, "Invalid label"):
            score(self.labels, self.pred, self.root / "bad_truth", bootstrap=0)
        self.assertFalse((self.root / "bad_truth").exists())

    def test_verifier_rejects_truncation_and_tampered_code_before_compilation(self):
        data = self.root / "data"
        source_dir = self.root / "source"
        source_dir.mkdir()
        (source_dir / "statement.md").write_text("题面")
        data.mkdir()
        code = "int main(){}\n"
        (data / "code.cpp").write_text(code)
        solution = {"method_id": "method_1", "editorial_md": "推导", "std": {"language": "cpp17", "interface": "stdin_stdout", "code": code}}
        write_jsonl(data / "inputs.jsonl", [{"id": "a", "statement_md": "题面", "solutions": [solution]}])
        p = {"id": "a", "problem_id": "P1", "source_dir": "source", "selections": []}
        write_jsonl(data / "provenance.jsonl", [p])
        with self.assertRaisesRegex(ValueError, "count mismatch"):
            verify(self.root, data, self.root / "verify.json", "/bin/false")
        p["selections"] = [{"method_id": "method_1", "std_path": "code.cpp", "input_code_sha256": sha(code)}]
        write_jsonl(data / "provenance.jsonl", [p])
        (data / "code.cpp").write_text("int main(){return 1;}\n")
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            verify(self.root, data, self.root / "verify.json", "/bin/false")
        self.assertFalse((self.root / "verify.json").exists())


class SourceIntegrity(unittest.TestCase):
    def test_attachment_pointer_is_not_runnable_sample_data(self):
        text = "### 样例输入 #2\n```text\n见附件中的 a.in\n```\n### 样例输出 #2\n```text\n见附件中的 a.ans\n```\n"
        self.assertFalse(samples(text)[0]["available"])
        text = "### 样例输入 #2\n```text\n见 mountain2.in/ans\n这个样例满足测试点2的约束\n```\n### 样例输出 #2\n```text\n\n```\n"
        self.assertFalse(samples(text)[0]["available"])

    def test_float_checker_follows_statement_tolerance(self):
        settings = {"sample_check": "numeric_tokens", "abs_tolerance": 1e-7, "rel_tolerance": 1e-7}
        self.assertTrue(compare_output("3.78539816", "3.7853981633974474", settings))
        self.assertFalse(compare_output("3.78", "3.7853981633974474", settings))
        self.assertFalse(compare_output("nan", "3.7853981633974474", settings))
        self.assertFalse(compare_output("3 4", "3", settings))

    def test_code_fences_long_fences_and_eof(self):
        text = "x\n````cpp\nint main() {}\n````\ny\n```cpp\nint f() {}\n"
        self.assertEqual(code_blocks(text), [("cpp", "int main() {}\n"), ("cpp", "int f() {}\n")])

    def test_comments_do_not_destroy_literals(self):
        code = 'auto a="https://example/x"; // P1234\nauto b=R"x(/*literal*/)x";/*identity*/\n'
        cleaned = strip_cpp_comments(code)
        self.assertIn('"https://example/x"', cleaned)
        self.assertIn('R"x(/*literal*/)x"', cleaned)
        self.assertNotIn("P1234", cleaned)
        self.assertNotIn("identity", cleaned)

    def test_remove_metadata_preserve_math_and_story(self):
        original = "# [NOIP 2026] 题名\n## 描述\n为了提高游戏难度，限制次数为 $n\\log n$。\n这道题是紫题。\n[题解 P1234](https://x/P1234)\n"
        cleaned, audit = sanitize(original, statement=True)
        self.assertIn("$n\\log n$", cleaned)
        self.assertNotIn("紫题", cleaned)
        self.assertNotIn("P1234", cleaned)
        self.assertNotIn("https", cleaned)
        self.assertNotIn("NOIP 2026", cleaned)
        self.assertTrue(audit)

    def test_rating_clause_does_not_delete_adjacent_algorithm(self):
        text = "第二种贡献容易前缀和优化，都来做紫题了想必不需要多说。注意系数乘上 $-1$。\n这道题不难发现 $f_i=f_{i-1}+1$，于是线性递推。\n"
        cleaned, _ = sanitize(text)
        self.assertIn("前缀和优化", cleaned)
        self.assertIn("$-1$", cleaned)
        self.assertIn("$f_i=f_{i-1}+1$", cleaned)
        self.assertIn("线性递推", cleaned)
        self.assertNotIn("紫题", cleaned)

    def test_nested_link_cleanup_keeps_following_chinese_text(self):
        text = "同[题目[别名]](https://www.luogu.com.cn/problem/P5291)这题一样，回退数据结构，把线段树合并的过程直接存下来，然后处理查询。"
        cleaned, _ = sanitize(text)
        self.assertIn("回退数据结构", cleaned)
        self.assertIn("线段树合并的过程", cleaned)
        self.assertNotIn("https://", cleaned)


if __name__ == "__main__":
    unittest.main()
