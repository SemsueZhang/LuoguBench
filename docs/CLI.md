> 这是保留的严格CLI研究流程，可选使用。网站主流程只需上传一个JSONL答案文件，无需以下元数据或ZIP。
> 所有正式测试均应遵守 [统一 Prompt 与测试协议](../PROMPT.md)。`run` 自动使用同样的逐题输入，也可用 `export-prompts --bundle benchmark --out my-prompts` 离线导出完整请求。

# LuoguBench：参与测试

LuoguBench 测试模型对公开 OI 题目的难度评级与洛谷参考标签的一致性。数据包含 87 题，每题输入为题面、1–3 个不同解法的代表题解和配套 C++ std，输出为八档难度和中文理由。主指标是 Spearman 相关系数。

这些题目原本公开，模型可能识别或记忆题目。匿名化也不保证题目或题号无法被识别、还原。标签没有放进参与者包，只是为了避免直接把答案喂给模型和统一维护评分，不能据此排除训练污染或证明新题泛化。理由保留供查看，本版只自动评分等级预测。

Python 3.10+ 即可运行，不需要安装额外 Python 库。你拿到的包包含完整匿名输入、固定提示词、图片、校验清单、模型适配器接口与提交工具，不包含逐题标签、题号映射、维护者分族记录或历史逐题评分。

## 1. 校验输入

在解压后的目录运行：

```bash
python3 -m luogubench check-bundle benchmark
```

它会核对每题内容、评级提示词、输出 schema、图片和文件清单。不要修改 benchmark/。不同数据或提示词版本不能混作同一测试结果。

## 2. 接入自己的模型

复制 `adapters/example_adapter.py`，在 `predict(request)` 中调用你自己的模型客户端。框架不绑定服务商，也不读取、保存或分发 API key。

适配器是一个 Python 文件或可执行文件，接受标准输入中的一个 JSON 请求，只向标准输出写一个 JSON 响应。调试日志写标准错误。

请求主要字段：

```json
{
  "id": "匿名题目ID",
  "protocol_id": "isolated-text-v1",
  "messages": [{"role": "user", "content": "框架生成的完整固定提示词与该题材料"}],
  "response_schema": {"type": "object"},
  "model": "你声明的模型名",
  "generation": {"reasoning_effort": "medium", "temperature": null, "max_output_tokens": null}
}
```

返回恰好四个字段，不要打印 Markdown 代码围栏：

```json
{"id":"请求中的ID","level":5,"label":"提高","reason":"结合本题关键洞察、推导、所需知识与实现负担，说明等级及相邻档位边界。"}
```

若需要记录客户端实际返回的用量，可返回 `{"prediction": 上述对象, "usage": 客户端报告的用量}`。框架只记录适配器报告值，不推测费用或实际模型身份。

运行你的适配器：

```bash
python3 -m luogubench run --bundle benchmark --adapter my_adapter.py --model my-model --reasoning medium --out runs/my-model
```

先检查两题的接入可加 `--limit 2`，之后用相同命令加 `--resume` 完成其余题目。超时默认 180 秒，可用 `--timeout` 调整。失败题保留错误记录，恢复时只重试未得到有效输出的题，不覆盖已有有效预测。完整 87 题作答后才能提交。运行元数据保留适配器调用次数，重试情况需如实报告，不根据标签或得分重新选择答案。

先跑一个完全离线的流程演示：

```bash
python3 -m luogubench run --bundle benchmark --adapter adapters/demo_constant.py --model demo-only --out runs/demo
```

demo 每题都返回固定等级，带有显式演示标记，不能作为模型成绩。`example_adapter.py` 是接入模板，不是已经接好服务商的客户端。

## 3. 统一测试条件

主协议为 **isolated-text-v1**：每题全新会话，相同模型与生成参数，使用框架生成的固定提示词。关闭历史记忆、搜索、工具、检索、额外技能与带标签示例。本协议只使用文本，不查看图片。图片随包保留，供其他明确标注的协议使用。

每题启动一个独立适配器进程，并不自动保证服务端清除了会话。适配器需要自行确保每次模型请求没有其他题目的历史。模型、参数和执行方式由参与者声明，评分器无法独立认证商业模型后端或提示词是否真的被遵守。

如果使用自己的 Agent、图片工具或批量共享上下文，请保留完整运行记录，使用外部协议导入：

```bash
python3 -m luogubench import-run predictions.jsonl --bundle benchmark --model my-agent --out runs/my-agent
```

外部运行标为 `external-agent-v1`，与主协议分开比较。历史 Luna 的 3×29 题测试属于 `legacy-agent-3x29`，不能直接和新主协议混排。本次对外封装未额外调用真实模型。

## 4. 生成并发送提交包

```bash
python3 -m luogubench submit --bundle benchmark --run runs/my-model --out my-model-submission.zip
```

把这个 ZIP 发给 Benchmark 维护者。它仅含 `predictions.jsonl`、`run.json` 和 `submission.json`，不包含你的适配器、API key、原始日志或其他目录。

维护者校验版本、87 题完整性、字段与内容哈希后评分，返回汇总指标。缺失、重复、未知 ID、无效等级、等级与名称不符、空理由或版本不符都会被拒绝，不会静默删除题目后算一个更高的分数。

评分返回的 `public_result.json` 可以公开。Spearman 衡量难度顺序一致性，准确率衡量等级完全一致，MAE 衡量平均差几档。不要把 Spearman 0.94 写成“准确率94%”。

## 材料边界

标准输入中的 std 是经过整理和有限检查的参考程序，不保证全部通过原 OJ。一个原始缺失项目按同题官方题解方向补充了独立参考实现。两张辅助示意图失效，材料中有明确标记。数据是官方代表题的有意选择，不代表全部洛谷题库分布。

题面、题解、程序和图像来自第三方原始材料，保留各来源与原作者的权利，见 DATA_NOTICE.md。代码工具的许可范围单独说明。
