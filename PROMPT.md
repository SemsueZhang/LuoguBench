# 统一提示词与协议

数据版本 **0.2.0**，主协议 **isolated-text-v2**。87 道题的任务叙述与 147 份代表题解已重新撰写，题意、输入输出、数据范围与可用样例保留，移除来源旁注和未提供附件的识别性文件名。三张图片中的子任务范围表补充文字版。修改不等于消除公开题记忆。

唯一标准请求是 [docs/requests.jsonl](docs/requests.jsonl)，共87行，每行一题。共同提示词见 [docs/prompt.txt](docs/prompt.txt)，哈希清单见 [docs/prompt-manifest.json](docs/prompt-manifest.json)。它们由 benchmark/ 和 CLI 的同一函数生成。仓库不再同时保存另一份 requests.jsonl。

## 执行

1. 每题全新无历史上下文，只发送对应行原样的 messages。不同题不能继承父 Agent 分析或其他回答。
2. 评级者只用文本，不看图，不搜索、联网、读文件、运行代码或调用其他工具。rubric 与 protocol 规则相同。调度者可用工具派发、读取和保存结果。
3. 固定模型版本与生成参数，不增加技能、示例或自定义标尺。
4. 保留首次有效输出，仅调用失败或格式无效可用相同输入重试，记录原因，不按得分改答案。
5. 输出 id、level、label、reason。合并87行 JSON 为 answers.jsonl，一次提交。网站只评分 id 与 level，不能验证实际执行方式。

按 [AGENT_RUN.md](AGENT_RUN.md) 可自动调度全部题。只能共享历史时标注 external-agent-v1，另行报告，不能当成主协议结果。

<a id="batch"></a>
## 脚本入口

```bash
python3 -m luogubench run --bundle benchmark --adapter my_adapter.py --model my-model --reasoning medium --jobs 8 --out runs/my-model
```

中断后原命令加 --resume，保留已完成有效题，只补缺失题。不得混用不同模型、参数、材料或协议版本的结果。平台并发不足时降低 jobs。

离线重新导出标准请求：

```bash
python3 -m luogubench export-prompts --bundle benchmark --out regenerated-prompts
```

导出目录需为空，该命令不调用模型。输出 requests.jsonl、prompt.txt、manifest.json，与网站的 requests.jsonl、prompt.txt、prompt-manifest.json 分别对应。

## 指标

按完全命中率、相差不超过一档命中率、Spearman ρ 的顺序报告。相差不超过一档包含完全命中，条件是绝对档位误差不超过一，目标100%。Spearman 使用并列平均秩，目标1.0000，常数预测为 null。目标不是实测保证，相关系数也不是准确率。不合成为单一总分。

旧数据0.1.0、旧标尺或旧协议的成绩仅作历史记录。新版尚未产生真实模型成绩，不能用旧结果替代。
