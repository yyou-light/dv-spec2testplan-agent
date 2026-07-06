import contextlib
import io
import unittest

from extractor import SKILL_LIBRARY, parse_skill_rules, route_dynamic_skills


class SkillRuleTests(unittest.TestCase):
    def test_numbered_skill_rules_are_loaded_with_source_refs(self):
        axi_rules = SKILL_LIBRARY["AXI"]["implicit_rules"]
        source_refs = [rule["source_ref"] for rule in axi_rules]

        self.assertIn(
            "[SKILL: axi.md#AXI-IMP-004] 通道反压：确保各通道在正常工作情况下，都触发过反压(ready拉低)。",
            source_refs,
        )

    def test_route_dynamic_skills_includes_reviewable_skill_refs(self):
        with contextlib.redirect_stdout(io.StringIO()):
            mounted = route_dynamic_skills("AXI ready valid handshake with SRAM access")

        self.assertIn("[SKILL: axi.md#AXI-IMP-004]", mounted)
        self.assertIn("[SKILL: sram.md#SRAM-IMP-001]", mounted)
        self.assertIn("Spec 中没有合适的直接支撑句", mounted)

    def test_unnumbered_rules_remain_compatible(self):
        rules = parse_skill_rules(
            "1. 老格式规则：覆盖连续传输。\n2. 老格式规则：覆盖异常响应。",
            "LEGACY",
            "legacy.md",
            "implicit",
        )

        self.assertEqual(rules[0]["id"], "LEGACY-IMP-AUTO-001")
        self.assertEqual(rules[1]["id"], "LEGACY-IMP-AUTO-002")
        self.assertIn("[SKILL: legacy.md#LEGACY-IMP-AUTO-001]", rules[0]["source_ref"])


if __name__ == "__main__":
    unittest.main()
