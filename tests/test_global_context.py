import json
import unittest
from types import SimpleNamespace

from planner import generate_chunking_plan


class RecordingCompletions:
    def __init__(self, payload: dict):
        self.payload = payload
        self.messages = None

    def create(self, **kwargs):
        self.messages = kwargs["messages"]
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload, ensure_ascii=False)
                    )
                )
            ]
        )


class RecordingClient:
    def __init__(self, payload: dict):
        self.completions = RecordingCompletions(payload)
        self.chat = SimpleNamespace(completions=self.completions)


class GlobalContextPlanningTests(unittest.TestCase):
    def test_planner_reads_full_spec_and_returns_evidenced_facts(self):
        payload = {
            "global_context": {
                "module_name": "AXI Bridge",
                "module_summary": "AXI 到 SRAM 桥接器。",
                "confirmed_facts": [
                    {
                        "fact_id": "GF-RESET-001",
                        "topic": "clock_reset",
                        "subject": "aresetn",
                        "value": "低电平异步复位，同步释放",
                        "section": "2.1 全局信号",
                        "evidence": "aresetn 低电平异步复位，同步释放。",
                    }
                ],
                "unresolved_questions": [],
            },
            "merge_groups": [
                {"group_name": "全局接口", "sections": ["1. Overview", "2.1 全局信号"]}
            ],
            "planning_reasoning": "接口和复位放在同一上下文中。",
        }
        client = RecordingClient(payload)
        markdown_text = (
            "# AXI Bridge\n\n"
            "## 1. Overview\nAXI 到 SRAM。\n\n"
            "## 2.1 全局信号\naresetn 低电平异步复位，同步释放。\n"
        )

        plan = generate_chunking_plan(
            client,
            "test-model",
            markdown_text,
            "- AXI Bridge\n  - 1. Overview\n  - 2.1 全局信号",
        )

        user_prompt = client.completions.messages[1]["content"]
        self.assertIn("aresetn 低电平异步复位，同步释放", user_prompt)
        self.assertEqual(plan.global_context.confirmed_facts[0].fact_id, "GF-RESET-001")
        self.assertEqual(plan.global_context.confirmed_facts[0].section, "2.1 全局信号")


if __name__ == "__main__":
    unittest.main()
