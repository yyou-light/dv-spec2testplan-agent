import json
import unittest
from types import SimpleNamespace

from cluster import (
    PRIMARY_CATEGORY_GUIDE,
    apply_testpoint_splits,
    build_testpoint_tree,
    classify_testpoints,
    generate_classification_taxonomy,
    review_testpoint_atomicity,
    resolve_category_gaps,
    split_mixed_testpoints,
    validate_classification_result,
)
from schemas import (
    ClassificationTaxonomy,
    IndexedTestpoint,
    RawTestpoint,
    TestpointClassificationResult,
)


class RecordingCompletions:
    def __init__(self, payloads: list[dict]):
        self.payloads = list(payloads)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        payload = self.payloads.pop(0)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(payload, ensure_ascii=False)
                    )
                )
            ]
        )


class RecordingClient:
    def __init__(self, payloads: list[dict]):
        self.completions = RecordingCompletions(payloads)
        self.chat = SimpleNamespace(completions=self.completions)


def make_point(testpoint_id: str, summary: str, details: str) -> IndexedTestpoint:
    return IndexedTestpoint(
        testpoint_id=testpoint_id,
        source_chunk="地址与边界",
        testpoint=RawTestpoint(
            raw_tag=summary,
            summary=summary,
            details=details,
            spec_quote="[4 地址] SRAM合法范围是0x0000到0xFFFF。",
            priority="P1",
            is_spec_ambiguous=False,
            ambiguity_note="",
        ),
    )


class ClusterClassificationTests(unittest.TestCase):
    def setUp(self):
        self.points = [
            make_point(
                "RTP_0001",
                "验证SRAM最高合法地址访问",
                "使用最高合法对齐地址发起普通读访问并返回OKAY。",
            ),
            make_point(
                "RTP_0002",
                "验证Burst递增越过SRAM范围",
                "首地址合法但后续地址越界时返回错误且停止非法访问。",
            ),
            make_point(
                "RTP_0003",
                "验证最大Outstanding反压期间复位",
                "达到最大Outstanding并持续反压时触发复位，验证状态恢复。",
            ),
        ]
        self.taxonomy_payload = {
            "secondary_categories": [
                {
                    "category_id": "FUNC-SRAM-ADDR",
                    "primary_category": "2.功能类",
                    "name": "SRAM合法地址访问",
                    "description": "SRAM支持范围内的正常地址译码和访问。",
                },
                {
                    "category_id": "EXC-SRAM-ADDR",
                    "primary_category": "4.异常类",
                    "name": "SRAM地址越界",
                    "description": "超过合法地址范围后的错误处理。",
                },
                {
                    "category_id": "CORNER-RESET-PRESSURE",
                    "primary_category": "6.corner类",
                    "name": "极限压力下复位",
                    "description": "资源极限、反压和复位同时发生的临界交互。",
                },
            ]
        }
        self.assignment_payload = {
            "assignments": [
                {
                    "testpoint_id": "RTP_0001",
                    "primary_category": "2.功能类",
                    "secondary_category_id": "FUNC-SRAM-ADDR",
                    "category_fit": True,
                    "category_fit_reason": "目录明确覆盖合法SRAM地址访问。",
                    "legality": "legal_supported",
                    "verification_intent": "normal_function",
                    "outcome_focus": "normal_supported_behavior",
                    "error_mechanisms": [],
                    "corner_triggers": [],
                    "corner_evidence": "",
                    "reasoning": "合法最高地址仍属于正常地址访问功能。",
                    "confidence": "high",
                    "needs_split": False,
                    "split_reason": "",
                },
                {
                    "testpoint_id": "RTP_0002",
                    "primary_category": "4.异常类",
                    "secondary_category_id": "EXC-SRAM-ADDR",
                    "category_fit": True,
                    "category_fit_reason": "目录明确覆盖SRAM地址越界错误。",
                    "legality": "defined_error_condition",
                    "verification_intent": "error_handling",
                    "outcome_focus": "single_error_handling",
                    "error_mechanisms": ["SRAM地址越界"],
                    "corner_triggers": [],
                    "corner_evidence": "",
                    "reasoning": "测试意图是越界后的错误响应。",
                    "confidence": "high",
                    "needs_split": False,
                    "split_reason": "",
                },
                {
                    "testpoint_id": "RTP_0003",
                    "primary_category": "6.corner类",
                    "secondary_category_id": "CORNER-RESET-PRESSURE",
                    "category_fit": True,
                    "category_fit_reason": "目录明确覆盖极限压力下复位。",
                    "legality": "legal_supported",
                    "verification_intent": "corner_interaction",
                    "outcome_focus": "state_or_resource_interaction",
                    "error_mechanisms": [],
                    "corner_triggers": ["multi_constraint_extreme"],
                    "corner_evidence": "最大Outstanding、持续反压与复位叠加。",
                    "reasoning": "多个极限状态和临界转换叠加。",
                    "confidence": "high",
                    "needs_split": False,
                    "split_reason": "",
                },
            ]
        }

    def test_primary_guide_keeps_corner_and_distinguishes_legal_boundary(self):
        self.assertIn("6.corner类", PRIMARY_CATEGORY_GUIDE)
        self.assertIn("合法最小值和最大值", PRIMARY_CATEGORY_GUIDE["2.功能类"])
        self.assertIn("多个约束叠加", PRIMARY_CATEGORY_GUIDE["6.corner类"])

    def test_classifier_reads_complete_testpoints_and_global_context(self):
        client = RecordingClient([self.taxonomy_payload, self.assignment_payload])
        global_context = {
            "confirmed_facts": [
                {"subject": "SRAM range", "value": "0x0000到0xFFFF"}
            ]
        }

        taxonomy = generate_classification_taxonomy(
            client, "test-model", global_context, self.points
        )
        result = classify_testpoints(
            client, "test-model", global_context, self.points, taxonomy
        )

        classifier_prompt = client.completions.calls[1]["messages"][1]["content"]
        classifier_system_prompt = client.completions.calls[1]["messages"][0]["content"]
        self.assertIn("使用最高合法对齐地址发起普通读访问并返回OKAY", classifier_prompt)
        self.assertIn("SRAM合法范围是0x0000到0xFFFF", classifier_prompt)
        self.assertIn("confirmed_facts", classifier_prompt)
        self.assertIn("分类阶段只负责目录归属", classifier_system_prompt)
        self.assertIn("组合后的刺激仍在合法支持域内", classifier_system_prompt)
        self.assertIn("outcome_focus", classifier_system_prompt)
        self.assertEqual(result.assignments[0].primary_category, "2.功能类")

        tree = build_testpoint_tree(self.points, taxonomy, result)
        self.assertIn("2.功能类", tree)
        self.assertIn("4.异常类", tree)
        self.assertIn("6.corner类", tree)

    def test_missing_assignment_is_rejected(self):
        taxonomy = ClassificationTaxonomy.model_validate(self.taxonomy_payload)
        incomplete = TestpointClassificationResult.model_validate(
            {"assignments": self.assignment_payload["assignments"][:-1]}
        )

        with self.assertRaisesRegex(ValueError, "漏分类"):
            validate_classification_result(self.points, taxonomy, incomplete)

    def test_taxonomy_schema_error_is_repaired(self):
        invalid_taxonomy = json.loads(
            json.dumps(self.taxonomy_payload, ensure_ascii=False)
        )
        invalid_taxonomy["secondary_categories"][0]["category_ID"] = (
            invalid_taxonomy["secondary_categories"][0].pop("category_id")
        )
        client = RecordingClient([invalid_taxonomy, self.taxonomy_payload])

        taxonomy = generate_classification_taxonomy(
            client,
            "test-model",
            {"confirmed_facts": []},
            self.points,
        )

        self.assertEqual(len(client.completions.calls), 2)
        self.assertEqual(
            taxonomy.secondary_categories[0].category_id,
            "FUNC-SRAM-ADDR",
        )

    def test_business_rule_error_is_repaired(self):
        invalid_assignment = json.loads(
            json.dumps(self.assignment_payload, ensure_ascii=False)
        )
        invalid_assignment["assignments"][2]["legality"] = (
            "unsupported_or_illegal"
        )
        client = RecordingClient([invalid_assignment, self.assignment_payload])
        taxonomy = ClassificationTaxonomy.model_validate(self.taxonomy_payload)

        result = classify_testpoints(
            client,
            "test-model",
            {"confirmed_facts": []},
            self.points,
            taxonomy,
        )

        self.assertEqual(len(client.completions.calls), 2)
        self.assertEqual(result.assignments[2].legality, "legal_supported")

    def test_missing_secondary_category_is_added_and_only_gap_is_reclassified(self):
        initial_payload = json.loads(
            json.dumps(self.assignment_payload, ensure_ascii=False)
        )
        gap = initial_payload["assignments"][2]
        gap["secondary_category_id"] = ""
        gap["category_fit"] = False
        gap["category_fit_reason"] = "现有目录没有覆盖复位与在途事务重叠。"
        gap["proposed_secondary_category"] = {
            "category_id": "CORNER-RESET-INFLIGHT",
            "primary_category": "6.corner类",
            "name": "复位与在途事务",
            "description": "复位转换与未完成或持续请求重叠的临界交互。",
        }
        repaired_assignment = json.loads(
            json.dumps(self.assignment_payload["assignments"][2], ensure_ascii=False)
        )
        repaired_assignment["secondary_category_id"] = "CORNER-RESET-INFLIGHT"
        repaired_assignment["category_fit_reason"] = "新目录准确覆盖复位与在途事务重叠。"
        client = RecordingClient([{"assignments": [repaired_assignment]}])
        taxonomy = ClassificationTaxonomy.model_validate(self.taxonomy_payload)
        initial = TestpointClassificationResult.model_validate(initial_payload)

        expanded, repaired = resolve_category_gaps(
            client,
            "test-model",
            {"confirmed_facts": []},
            self.points,
            taxonomy,
            initial,
        )

        self.assertIn(
            "CORNER-RESET-INFLIGHT",
            {category.category_id for category in expanded.secondary_categories},
        )
        self.assertEqual(len(client.completions.calls), 1)
        self.assertTrue(repaired.assignments[2].category_fit)
        self.assertEqual(
            repaired.assignments[2].secondary_category_id,
            "CORNER-RESET-INFLIGHT",
        )

    def test_corner_requires_supported_or_ambiguous_triggered_interaction(self):
        taxonomy = ClassificationTaxonomy.model_validate(self.taxonomy_payload)
        invalid_payload = json.loads(json.dumps(self.assignment_payload, ensure_ascii=False))
        corner = invalid_payload["assignments"][2]
        corner["legality"] = "unsupported_or_illegal"
        corner["corner_triggers"] = []
        corner["corner_evidence"] = ""
        invalid = TestpointClassificationResult.model_validate(invalid_payload)

        with self.assertRaisesRegex(ValueError, "corner 触发条件或合法性无效"):
            validate_classification_result(self.points, taxonomy, invalid)

    def test_single_boundary_error_cannot_be_ambiguous_multi_constraint_corner(self):
        taxonomy = ClassificationTaxonomy.model_validate(self.taxonomy_payload)
        invalid_payload = json.loads(
            json.dumps(self.assignment_payload, ensure_ascii=False)
        )
        boundary = invalid_payload["assignments"][1]
        boundary.update(
            {
                "primary_category": "6.corner类",
                "secondary_category_id": "CORNER-RESET-PRESSURE",
                "category_fit_reason": "错误地把合法起点和Burst长度视为多约束极限。",
                "legality": "spec_ambiguous",
                "verification_intent": "corner_interaction",
                "outcome_focus": "state_or_resource_interaction",
                "error_mechanisms": [],
                "corner_triggers": ["multi_constraint_extreme"],
                "corner_evidence": "合法首地址与合法Burst长度组合后跨出地址范围。",
            }
        )
        invalid = TestpointClassificationResult.model_validate(invalid_payload)

        with self.assertRaisesRegex(ValueError, "corner 触发条件或合法性无效"):
            validate_classification_result(self.points, taxonomy, invalid)

    def test_multiple_error_priority_remains_a_valid_corner(self):
        point = make_point(
            "RTP_0301",
            "验证非对齐且越界请求的错误优先级",
            "同一请求同时命中非对齐SLVERR和地址越界DECERR，验证响应优先级。",
        )
        taxonomy = ClassificationTaxonomy.model_validate(
            {
                "secondary_categories": [
                    {
                        "category_id": "CORNER-ERROR-PRIORITY",
                        "primary_category": "6.corner类",
                        "name": "多错误优先级",
                        "description": "多个独立错误机制同时命中时的优先级交互。",
                    }
                ]
            }
        )
        result = TestpointClassificationResult.model_validate(
            {
                "assignments": [
                    {
                        "testpoint_id": "RTP_0301",
                        "primary_category": "6.corner类",
                        "secondary_category_id": "CORNER-ERROR-PRIORITY",
                        "category_fit": True,
                        "category_fit_reason": "目录覆盖两个独立错误机制的优先级。",
                        "legality": "spec_ambiguous",
                        "verification_intent": "corner_interaction",
                        "outcome_focus": "multiple_error_interaction",
                        "error_mechanisms": ["非对齐SLVERR", "地址越界DECERR"],
                        "corner_triggers": ["multiple_error_interaction"],
                        "corner_evidence": "同一请求同时命中两个独立错误条件。",
                        "reasoning": "重点是错误机制交互，不是重复验证单一错误。",
                        "confidence": "high",
                    }
                ]
            }
        )

        validate_classification_result([point], taxonomy, result)

    def test_only_flagged_mixed_point_is_split_without_touching_other_points(self):
        mixed_result = TestpointClassificationResult.model_validate(
            {
                "assignments": [
                    {
                        **self.assignment_payload["assignments"][0],
                        "needs_split": True,
                        "split_reason": "同时包含合法和非法地址行为。",
                    },
                    *self.assignment_payload["assignments"][1:],
                ]
            }
        )
        original = self.points[0].testpoint.model_dump()
        split_payload = {
            "splits": [
                {
                    "original_testpoint_id": "RTP_0001",
                    "rationale": "合法访问和越界错误响应需要不同预期。",
                    "normal_completion_present": True,
                    "error_response_present": True,
                    "single_invariant_or_scenario": False,
                    "unresolved_design_alternatives": False,
                    "separable_stimulus_classes": True,
                    "replacements": [
                        {
                            **original,
                            "summary": "验证SRAM最高合法地址访问",
                            "details": "最高合法地址读取返回OKAY。",
                        },
                        {
                            **original,
                            "summary": "验证超过SRAM最高地址的访问",
                            "details": "越界读取返回DECERR且不访问SRAM。",
                        },
                    ],
                }
            ],
            "kept_testpoints": [],
        }

        review = split_mixed_testpoints(
            RecordingClient([split_payload]),
            "test-model",
            {"confirmed_facts": []},
            self.points,
            mixed_result,
        )
        split_points = apply_testpoint_splits(self.points, review)

        self.assertEqual(
            [point.testpoint_id for point in split_points],
            ["RTP_0001-S1", "RTP_0001-S2", "RTP_0002", "RTP_0003"],
        )
        self.assertEqual(split_points[2].testpoint.summary, self.points[1].testpoint.summary)

    def test_atomicity_review_preserves_sweeps_and_intentional_corner_combinations(self):
        legal_sweep = make_point(
            "RTP_0101",
            "遍历所有合法地址边界",
            "覆盖最低地址、最高合法字地址和区间内地址，均按正常访问返回OKAY。",
        )
        mixed_legality = make_point(
            "RTP_0102",
            "遍历AXI size和length组合",
            "支持的组合应正常完成，超过支持范围的组合应返回错误响应。",
        )
        corner_combo = make_point(
            "RTP_0103",
            "最大Outstanding反压期间复位",
            "达到最大Outstanding并持续反压时触发复位，验证组合状态恢复。",
        )
        original = mixed_legality.testpoint.model_dump()
        review_payload = {
            "splits": [
                {
                    "original_testpoint_id": "RTP_0102",
                    "rationale": "合法组合和非法组合具有不同预期响应。",
                    "normal_completion_present": True,
                    "error_response_present": True,
                    "single_invariant_or_scenario": False,
                    "unresolved_design_alternatives": False,
                    "separable_stimulus_classes": True,
                    "replacements": [
                        {
                            **original,
                            "summary": "遍历AXI支持的size和length组合",
                            "details": "所有支持组合均正常完成并返回OKAY。",
                        },
                        {
                            **original,
                            "summary": "遍历AXI不支持的size和length组合",
                            "details": "所有不支持组合均返回规定的错误响应。",
                        },
                    ],
                }
            ],
            "kept_testpoints": [
                {
                    "testpoint_id": "RTP_0101",
                    "rationale": "合法地址范围共享正常访问预期。",
                    "normal_completion_present": True,
                    "error_response_present": False,
                    "single_invariant_or_scenario": False,
                    "unresolved_design_alternatives": False,
                    "separable_stimulus_classes": False,
                },
                {
                    "testpoint_id": "RTP_0103",
                    "rationale": "多个极限条件共同构成一个corner交互。",
                    "normal_completion_present": True,
                    "error_response_present": False,
                    "single_invariant_or_scenario": True,
                    "unresolved_design_alternatives": False,
                    "separable_stimulus_classes": False,
                },
            ],
        }
        client = RecordingClient([review_payload])

        review = review_testpoint_atomicity(
            client,
            "test-model",
            {"confirmed_facts": []},
            [legal_sweep, mixed_legality, corner_combo],
            batch_size=3,
        )
        reviewed_points = apply_testpoint_splits(
            [legal_sweep, mixed_legality, corner_combo],
            review,
        )

        self.assertEqual(
            [point.testpoint_id for point in reviewed_points],
            ["RTP_0101", "RTP_0102-S1", "RTP_0102-S2", "RTP_0103"],
        )
        system_prompt = client.completions.calls[0]["messages"][0]["content"]
        self.assertIn("不要拆分同一行为的参数遍历", system_prompt)
        self.assertIn("不要拆分刻意叠加的 corner 条件", system_prompt)
        self.assertIn("拿不准时保留原测试点", system_prompt)
        self.assertIn("拆分不能替代需求澄清", system_prompt)
        self.assertIn("不能作为漏拆豁免", system_prompt)

    def test_atomicity_over_split_is_repaired(self):
        gating = make_point(
            "RTP_0201",
            "验证sram_en门控不变量",
            "合法访问时拉高，无事务、复位或错误请求时保持低电平。",
        )
        original = gating.testpoint.model_dump()
        invalid_review = {
            "splits": [
                {
                    "original_testpoint_id": "RTP_0201",
                    "rationale": "按高低电平条件拆分。",
                    "normal_completion_present": True,
                    "error_response_present": False,
                    "single_invariant_or_scenario": True,
                    "unresolved_design_alternatives": False,
                    "separable_stimulus_classes": False,
                    "replacements": [
                        {**original, "summary": "访问时sram_en拉高"},
                        {**original, "summary": "无访问时sram_en拉低"},
                    ],
                }
            ],
            "kept_testpoints": [],
        }
        corrected_review = {
            "splits": [],
            "kept_testpoints": [
                {
                    "testpoint_id": "RTP_0201",
                    "rationale": "高低电平条件共同定义一个门控不变量。",
                    "normal_completion_present": True,
                    "error_response_present": False,
                    "single_invariant_or_scenario": True,
                    "unresolved_design_alternatives": False,
                    "separable_stimulus_classes": False,
                }
            ],
        }
        client = RecordingClient([invalid_review, corrected_review])

        review = review_testpoint_atomicity(
            client,
            "test-model",
            {"confirmed_facts": []},
            [gating],
            batch_size=1,
        )

        self.assertEqual(review.splits, [])
        self.assertEqual(len(client.completions.calls), 2)

    def test_atomicity_missed_split_is_repaired(self):
        mixed = make_point(
            "RTP_0202",
            "遍历合法和非法size length组合",
            "合法组合返回OKAY，超过范围的组合返回SLVERR。",
        )
        original = mixed.testpoint.model_dump()
        missed_review = {
            "splits": [],
            "kept_testpoints": [
                {
                    "testpoint_id": "RTP_0202",
                    "rationale": "作为一个交叉遍历保留。",
                    "normal_completion_present": True,
                    "error_response_present": True,
                    "single_invariant_or_scenario": False,
                    "unresolved_design_alternatives": True,
                    "separable_stimulus_classes": True,
                }
            ],
        }
        corrected_review = {
            "splits": [
                {
                    "original_testpoint_id": "RTP_0202",
                    "rationale": "正常完成和错误响应必须分开。",
                    "normal_completion_present": True,
                    "error_response_present": True,
                    "single_invariant_or_scenario": False,
                    "unresolved_design_alternatives": True,
                    "separable_stimulus_classes": True,
                    "replacements": [
                        {**original, "summary": "遍历合法size length组合"},
                        {**original, "summary": "遍历非法size length组合"},
                    ],
                }
            ],
            "kept_testpoints": [],
        }
        client = RecordingClient([missed_review, corrected_review])

        review = review_testpoint_atomicity(
            client,
            "test-model",
            {"confirmed_facts": []},
            [mixed],
            batch_size=1,
        )

        self.assertEqual(
            [split.original_testpoint_id for split in review.splits],
            ["RTP_0202"],
        )
        self.assertEqual(len(client.completions.calls), 2)

    def test_unused_taxonomy_category_does_not_create_numbering_gap(self):
        taxonomy_payload = json.loads(
            json.dumps(self.taxonomy_payload, ensure_ascii=False)
        )
        taxonomy_payload["secondary_categories"].append(
            {
                "category_id": "FUNC-A-UNUSED",
                "primary_category": "2.功能类",
                "name": "未使用目录",
                "description": "模型规划但没有测试点采用的目录。",
            }
        )
        taxonomy = ClassificationTaxonomy.model_validate(taxonomy_payload)
        result = TestpointClassificationResult.model_validate(
            self.assignment_payload
        )

        tree = build_testpoint_tree(self.points, taxonomy, result)

        self.assertEqual(
            list(tree["2.功能类"]),
            ["2.1 SRAM合法地址访问"],
        )


if __name__ == "__main__":
    unittest.main()
