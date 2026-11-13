"""Offline wiring demo. This is a fixed response, never a model benchmark result."""
import json
import sys

request = json.load(sys.stdin)
json.dump({"prediction": {"id": request["id"], "level": 4, "label": "普及+/提高-",
                          "reason": "接口演示返回的固定等级，仅用于确认读取、运行、提交和评分链路正常，不代表任何模型的实际评级能力。"},
           "demo": True}, sys.stdout, ensure_ascii=False)
