# 可选的严格 CLI 流程

网站只需一个完整 JSONL，以下步骤用于需要保留运行元数据与版本校验的测试。工具0.3.0、数据0.2.0、协议isolated-text-v2，核心指标为完全命中率、相差不超过一档命中率、Spearman。

在任务包根目录执行，无需额外Python依赖：

```bash
python3 -m luogubench check-bundle benchmark
python3 -m luogubench export-prompts --bundle benchmark --out my-prompts
python3 -m luogubench run --bundle benchmark --adapter my_adapter.py --model my-model --reasoning medium --jobs 8 --out runs/my-model
```

前两条不调用模型。适配器需接入你已有的模型客户端，每题只发单题messages、禁用工具和历史。模型身份及服务端是否隔离由参与者声明，框架不能认证。`--limit 2` 可试接入，原命令加 `--resume` 继续缺失题，保留已有有效回答。

完成后，runs/my-model/predictions.jsonl 可以直接在网站评分。需要严格提交包时执行：

```bash
python3 -m luogubench submit --bundle benchmark --run runs/my-model --out my-model-submission.zip
```

仅收集predictions.jsonl、run.json、submission.json，不包含模型适配器、密钥或其他目录。维护者用保留标签执行grade，不能把私有维护者包当作参与者材料。

外部Agent自行生成的完整预测，可用import-run导入，协议标external-agent-v1，与主协议分开。含工具、图片、共享上下文或额外技能的运行也不能声称主协议成绩。标准调度说明只维护根目录AGENT_RUN.md，标准请求只维护docs/requests.jsonl。

仅检查流水线时可使用adapters/demo_constant.py，它会明确标记is_demo，不能作为模型成绩。理由保留但不自动评分，完整87题才作正式比较。不按标签修改、删选或重试已有有效预测。

参考程序经过编译与适用样例检查，库接口及非唯一构造的跳过项单列。有限检查不等于原OJ验收。全部范围已在文本中给出，包括三张子任务图的转录。本版未运行真实模型，旧版分数不搬用。
