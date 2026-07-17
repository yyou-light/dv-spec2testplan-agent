import json
import unittest
from types import SimpleNamespace

from extractor import get_skill_rule_catalog
from skill_router import build_chunk_skill_prompts, build_semantic_skill_routing_plan


class FakeCompletions:
    def __init__(self, payload: dict):
        self.payload = payload

    def create(self, **kwargs):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(self.payload, ensure_ascii=False)
                    )
                )
            ]
        )


class FakeClient:
    def __init__(self, payload: dict):
        self.chat = SimpleNamespace(completions=FakeCompletions(payload))


class SemanticSkillRouterTests(unittest.TestCase):
    def test_no_candidate_skill_returns_empty_plan_without_model_call(self):
        class FailIfCalledClient:
            @property
            def chat(self):
                raise AssertionError("无 Skill 候选时不应调用大模型")

        plan = build_semantic_skill_routing_plan(
            FailIfCalledClient(),
            "test-model",
            "# Configuration\nValues are stored internally.",
            [{"group_name": "配置", "content": "Values are stored internally."}],
            {"module_name": "Config Block", "confirmed_facts": []},
        )

        self.assertEqual(plan.applications, [])

    def test_missing_candidate_rule_is_rejected(self):
        catalog = get_skill_rule_catalog(["AXI"])
        incomplete_refs = list(catalog)[:-1]
        payload = {
            "applications": [
                {
                    "rule_ref": rule_ref,
                    "target_chunks": ["AXI接口"],
                    "rationale": "AXI规则",
                    "coverage_targets": [],
                }
                for rule_ref in incomplete_refs
            ]
        }

        with self.assertRaisesRegex(ValueError, "规则漏分配"):
            build_semantic_skill_routing_plan(
                FakeClient(payload),
                "test-model",
                "# Spec\nAXI4 slave interface.",
                [{"group_name": "AXI接口", "content": "AXI4 slave."}],
                {"module_name": "AXI Block", "confirmed_facts": []},
            )

    def test_all_axi_rules_are_assigned_without_per_chunk_keyword_repetition(self):
        catalog = get_skill_rule_catalog(["AXI"])
        payload = {
            "applications": [
                {
                    "rule_ref": rule_ref,
                    "target_chunks": ["AXI接口与事务"],
                    "rationale": "完整 Spec 已确认 AXI4 Slave 接口。",
                    "coverage_targets": ["AXI接口"],
                }
                for rule_ref in catalog
            ]
        }
        chunks = [
            {"group_name": "AXI接口与事务", "content": "AXI4 slave read and write behavior."},
            {"group_name": "复位", "content": "aresetn resets the module."},
        ]

        plan = build_semantic_skill_routing_plan(
            FakeClient(payload),
            "test-model",
            "# Spec\nAXI4 slave interface.",
            chunks,
            {"module_name": "AXI Bridge", "confirmed_facts": []},
        )

        self.assertEqual(
            {application.rule_ref for application in plan.applications},
            set(catalog),
        )
        prompts = build_chunk_skill_prompts(plan)
        self.assertIn("[SKILL: axi.md#AXI-IMP-004]", prompts["AXI接口与事务"])
        self.assertNotIn("复位", prompts)


if __name__ == "__main__":
    unittest.main()
