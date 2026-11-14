# LuoguBench

评测模型对公开 OI 题目的难度评级与参考标签的一致性。输入为87道题的改写题面、147份不同算法族的代表题解及配套参考程序，输出洛谷2026新版八档难度。

[在线评分](https://semsuezhang.github.io/LuoguBench/) · [统一 Prompt](PROMPT.md) · [Agent 使用说明](AGENT_RUN.md) · [数据说明](DATASET_CARD.md)

## 使用

1. 下载评测包，或让 Agent 使用本仓库，按 AGENT_RUN.md 自动完成87题。
2. 使用同一模型、参数与逐题全新上下文。评级者仅用文本，不看图、不调用工具。按 docs/requests.jsonl 的固定消息生成回答。
3. 将每题 JSON 合并为一个 answers.jsonl，在网站一次上传。网站只在浏览器评分，不上传文件。

```json
{"id":"输入中的题目ID","level":5,"label":"提高","reason":"结合本题关键推导与实现说明相邻档边界。"}
```

87个ID必须完整且不重复，level 是1–8整数。网站允许省略 label、reason 进行等级评分，但不能据此证明执行了完整协议。正式模型输出应保留这两个字段，理由质量不自动评分。

## 三项核心指标

| 指标 | 含义 | 目标 |
|---|---|---|
| 完全命中率 | 预测档位等于参考档位 | 越高越好 |
| 相差不超过一档 | 绝对档位误差≤1，包含完全命中 | 100% |
| Spearman ρ | 并列平均秩的相关系数 | 1.0000 |

目标值与实测值分开，不合成总分。常数预测的 Spearman 未定义，报告 null，不写成零。MAE、偏差与混淆矩阵用于诊断。完整87题才作正式比较。

## 版本与边界

工具0.3.0，数据0.2.0，主协议 isolated-text-v2。全部任务叙述和代表题解重新撰写，技术规格与可用样例保留，来源旁注与未提供附件的识别性文件名移除，三张子任务表补充文字。4/5/6档以独立建模、证明、优化和实现的实际门槛区分，不按关键结论数量分档，也不强求各档数量均匀。

公开题仍可能被识别或记忆。代码、样例、数据范围与数学结构也可能保留识别线索，改写不构成无污染或新题能力证明。旧0.1.0结果不能与新版混排，本版未重跑真实模型。

AGENT_RUN.md 是唯一Agent说明，docs/requests.jsonl 是唯一标准请求文件。下载包、网页和CLI由同一输入生成并校验哈希。

## 可选 CLI

Python3.10+，标准库即可，接入你已有的模型适配器后运行：

```bash
python3 -m luogubench check-bundle benchmark
python3 -m luogubench run --bundle benchmark --adapter my_adapter.py --model my-model --jobs 8 --out runs/my-model
```

原命令加 --resume 可继续缺失题。最终上传 runs/my-model/predictions.jsonl。调度脚本不认证模型身份或服务端上下文隔离。详细步骤见 [CLI](docs/CLI.md)。

## 网站源码

本仓库 docs/ 中的 HTML、CSS、原生JS为静态评分页面，直接用于GitHub Pages。主内容字号18–20px，核心指标大字显示。

```bash
python3 -m http.server 8000 --directory docs
python3 -m unittest discover -s tests -q
node --test web-tests/*.test.mjs
```

浏览器评分数据可从源码取得，不能作为保密机制。第三方题目、程序与图像保留各来源权利，详见 DATA_NOTICE.md，工具代码许可单列于 LICENSE-CODE。
