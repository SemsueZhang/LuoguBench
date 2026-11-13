# LuoguBench

一个测试模型对 **公开 OI 题目难度评级一致性** 的小型 Benchmark。包含87题，每题输入为题面、去重题解与std，预测洛谷2026新版八档难度，主指标为Spearman相关系数。

[在线评分网站](https://semsuezhang.github.io/LuoguBench/) · [下载参与者材料](https://github.com/SemsueZhang/LuoguBench/releases/download/v0.2.1/luogubench-participant-0.2.1.zip) · [统一 Prompt 与测试规则](PROMPT.md)

## 最简单的用法

1. 下载参与者材料，使用其中 [prompts/requests.jsonl](prompts/requests.jsonl) 的87条完整请求，每题开独立新会话，原样发送 `messages`，禁用工具。
2. 将模型的87个JSON对象各写一行，合并为 `answers.jsonl`。也可以使用 [answers-template.jsonl](answers-template.jsonl)，把每行的 `null` 替换为预测等级。
3. 在在线评分页面一次上传整个文件，即可得到汇总成绩。无需ZIP、运行元数据或后端服务。

```json
{"id":"材料中的题目ID","level":5}
```

一个 `answers.jsonl` 文件包含全部87题，每行一题，ID必须完整且不重复。顺序可以改变。已有的 `label`、`reason` 字段可以保留，但网站只读取 `id` 和 `level`。理由质量不自动评分。

## 统一 Prompt

正式协议为 `isolated-text-v1`。固定 [共同提示词](prompts/prompt.txt)、每题材料、单题新会话和禁用工具的执行方式，所有模型使用同样输入。正式模型输出包含 `id`、`level`、`label`、`reason` 四个字段，网站仍然只评分前两个字段，不增加上传要求。

完整规则见 [PROMPT.md](PROMPT.md)。87题请求由 CLI 实际使用的同一个函数生成，可离线重新导出：

```bash
python3 -m luogubench export-prompts --bundle benchmark --out my-prompts
```

本次工具更新为0.2.1，数据仍为0.1.0，冻结的逐题Prompt内容及指纹保持不变。统一Prompt不等于统一推理预算，对外比较时应说明模型版本和生成参数。网站无法验证参与者实际使用的提示词与执行设置。

[下载参与者材料](https://github.com/SemsueZhang/LuoguBench/releases/download/v0.2.1/luogubench-participant-0.2.1.zip)

## 网站

`docs/` 是完全静态的HTML、CSS和原生JavaScript，可直接部署GitHub Pages，不需要npm安装或构建。

```bash
python3 -m http.server 8000 --directory docs
```

然后打开 http://localhost:8000 。浏览器完成文件读取、格式检查和全部算分，不发送答案到服务器。参考评级以前端评分数据提供，界面不显示逐题标准答案。源码可被检查，这不构成保密或防污染机制。

## 数据与评分

- 87题，原始1340篇题解，207个算法族，最终147份代表输入
- 数据版本0.1.0，八档难度中的两个黑题子分组合并为第8档
- 同时报Spearman、Kendall、Pearson、准确率、MAE、±1档比例和加权Kappa
- 缺题、重复ID、未知ID、非1–8整数均拒绝，不删除无效条目后计算部分分数
- 常数预测的相关系数保存为null，不伪装成0
- 网页提交标记 `web-file-v1`，只检查答案数据，不验证模型身份或执行设置

旧版Luna medium在3×29共享上下文协议下，Spearman为0.9397，命中率55.2%，MAE0.5057。这是历史参考，不能当成逐题独立协议的新测试结果。详情见 [historical_baseline.json](historical_baseline.json)。

公开题可能被识别或记忆。这套数据衡量与洛谷参考标签的一致性，不能单独证明新题难度判断能力。参考程序经过编译与适用样例检查，不等于原OJ验收。来源与使用边界见 [DATASET_CARD.md](DATASET_CARD.md)、[DATA_NOTICE.md](DATA_NOTICE.md)。

## 可选的CLI

研究用的严格提交、协议记录与评分工具仍可使用，见 [CLI说明](docs/CLI.md)。网站不要求这些步骤。

```bash
python3 -m luogubench check-bundle benchmark
python3 -m unittest discover -s tests
node --test web-tests/*.test.mjs
```

工具代码许可见 LICENSE-CODE，第三方题面、题解、程序和图片保留其原来源的权利。
