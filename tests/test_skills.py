import contextlib
import io
import unittest

from extractor import (
    SKILL_LIBRARY,
    detect_skill_names,
    get_skill_rule_catalog,
    keyword_matches,
    parse_skill_rules,
    route_dynamic_skills,
)


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
        self.assertIn("每条非同义规则都必须至少落实", mounted)

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

    def test_keyword_matching_does_not_match_substrings_inside_words(self):
        self.assertFalse(keyword_matches("program configuration register", "ram"))
        self.assertFalse(keyword_matches("request is already accepted", "ready"))
        self.assertTrue(keyword_matches("AXI4 slave interface", "axi"))
        self.assertTrue(keyword_matches("`AWREADY` may be deasserted", "ready"))
        self.assertTrue(keyword_matches("write through `ram_en`", "ram"))

    def test_document_level_detection_keeps_protocol_skills(self):
        detected = detect_skill_names(
            "AXI4 slave converts requests to a single-port SRAM interface."
        )

        self.assertIn("AXI", detected)
        self.assertIn("SRAM", detected)
        catalog = get_skill_rule_catalog(detected)
        self.assertIn("axi.md#AXI-IMP-004", catalog)
        self.assertIn("sram.md#SRAM-IMP-001", catalog)

    def test_document_without_protocol_signal_has_no_skill_candidates(self):
        detected = detect_skill_names("Configuration values are stored internally.")

        self.assertEqual(detected, [])
        self.assertEqual(get_skill_rule_catalog(detected), {})


if __name__ == "__main__":
    unittest.main()
