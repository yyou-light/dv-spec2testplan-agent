import json
import os
import re
from collections import defaultdict

from schemas import (
    ClassificationTaxonomy,
    IndexedTestpoint,
    SecondaryCategory,
    TestpointAtomicityReview,
    TestpointClassificationResult,
)


PRIMARY_CATEGORY_GUIDE = {
    "1.接口类": (
        "验证 DUT 对外接口本身的基础属性和协议行为，包括信号方向与位宽、通道、握手、"
        "接口时序和协议规定的正常交互。"
    ),
    "2.功能类": (
        "验证 DUT 在 Spec 支持范围内的正常功能，包括合法配置、正常读写、地址译码、"
        "数据处理，以及合法最小值和最大值。合法边界值本身仍属于正常功能。"
    ),
    "3.场景类": (
        "验证多步骤、多接口、软件与硬件协作或完整业务流。场景必须体现组合使用流程，"
        "不能仅因为测试持续多拍或包含反压就归入场景。"
    ),
    "4.异常类": (
        "验证非法输入、不支持操作、越界、协议违规、错误响应和故障隔离。Spec 明确支持的"
        "乱序、边界或握手行为不属于异常。"
    ),
    "5.上报类": (
        "验证中断、状态、告警、错误码及其他以可观察上报机制为主要目的的行为。普通 AXI "
        "OKAY 响应或事务完成本身不自动归入上报。"
    ),
    "6.corner类": (
        "验证普通功能测试不易触发的极限状态、临界转换、罕见并发、资源饱和、恢复过程或"
        "多个约束叠加。出现边界、最大值、交叉等字样不等于 corner；单独合法端点仍是功能，"
        "多个约束叠加或临界状态交互才属于 corner。"
    ),
}

INTENT_TO_PRIMARY_CATEGORY = {
    "interface_contract": "1.接口类",
    "normal_function": "2.功能类",
    "workflow_scenario": "3.场景类",
    "error_handling": "4.异常类",
    "reporting": "5.上报类",
    "corner_interaction": "6.corner类",
}

OUTCOME_FOCUS_TO_INTENTS = {
    "normal_supported_behavior": {"interface_contract", "normal_function"},
    "single_error_handling": {"error_handling"},
    "workflow_behavior": {"workflow_scenario"},
    "reporting_behavior": {"reporting"},
    "state_or_resource_interaction": {"corner_interaction"},
    "multiple_error_interaction": {"corner_interaction"},
}

CORNER_TRIGGER_GUIDE = {
    "resource_saturation": (
        "明确达到实现支持的容量上限，例如最大 outstanding 或缓冲满；"
        "普通连续事务和 non-blocking 访问不算。"
    ),
    "sustained_stall_recovery": (
        "故意长时间保持反压并验证解除瞬间恢复；随机或短暂 ready 变化不算。"
    ),
    "concurrent_conflict": (
        "两个操作在同一时间窗口争用同一资源、地址或状态；普通背靠背包不算。"
    ),
    "critical_state_transition": (
        "复位、使能或模式切换与在途事务重叠；单独复位或普通配置流程不算。"
    ),
    "multi_constraint_extreme": (
        "至少两个各自合法的极限维度同时叠加，且组合后的刺激仍在合法支持域内；"
        "组合后跨入越界或非法域不算。"
    ),
    "multiple_error_interaction": (
        "同一刺激同时命中至少两个相互独立的错误机制，验证优先级或交互；"
        "单一越界条件、一次错误响应或一个错误机制的不同参数不算。"
    ),
}


def request_validated_json(
    client,
    model_name: str,
    messages: list[dict[str, str]],
    schema_type,
    label: str,
    validator=None,
    max_tokens: int = 8192,
):
    """Request structured output and let the model repair schema/business errors."""
    max_retries = int(os.getenv("DV_STRUCTURED_RETRY", "2"))
    if max_retries < 0:
        raise ValueError("DV_STRUCTURED_RETRY 不能小于 0")

    retry_messages = list(messages)
    last_error = None
    for attempt in range(max_retries + 1):
        response = client.chat.completions.create(
            model=model_name,
            messages=retry_messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        try:
            parsed = schema_type.model_validate_json(content)
            if validator is not None:
                validator(parsed)
            return parsed
        except ValueError as exc:
            last_error = exc
            if attempt >= max_retries:
                break
            print(
                f"  [警告] {label}结构化结果未通过校验，"
                f"正在纠正重试 {attempt + 1}/{max_retries}..."
            )
            retry_messages = list(messages) + [
                {"role": "assistant", "content": content},
                {
                    "role": "user",
                    "content": (
                        "上一次输出未通过 JSON Schema 或业务规则校验。"
                        "请根据下面错误修正，并重新输出完整 JSON 对象；"
                        "不要解释，不要省略未报错的记录。\n"
                        f"校验错误：{str(exc)[:3000]}"
                    ),
                },
            ]

    raise ValueError(f"{label}在自动纠正后仍无效: {last_error}") from last_error


def build_testpoint_payload(indexed_testpoints: list[IndexedTestpoint]) -> list[dict]:
    payload = []
    for indexed in indexed_testpoints:
        point = indexed.testpoint
        payload.append(
            {
                "testpoint_id": indexed.testpoint_id,
                "source_chunk": indexed.source_chunk,
                "raw_tag": point.raw_tag,
                "summary": point.summary,
                "details": point.details,
                "basis_reference": point.spec_quote,
                "priority": point.priority,
                "is_spec_ambiguous": point.is_spec_ambiguous,
                "ambiguity_note": point.ambiguity_note,
            }
        )
    return payload


def generate_classification_taxonomy(
    client,
    model_name: str,
    global_context: dict,
    indexed_testpoints: list[IndexedTestpoint],
) -> ClassificationTaxonomy:
    """Plan a compact set of reusable secondary categories under the fixed six DV classes."""
    schema_json = ClassificationTaxonomy.model_json_schema()
    point_payload = build_testpoint_payload(indexed_testpoints)
    system_prompt = f"""
你是资深数字 IC 验证架构师。请为当前 DUT 的测试点建立二级分类目录。

【固定一级目录及业务定义】
{json.dumps(PRIMARY_CATEGORY_GUIDE, ensure_ascii=False, indent=2)}

【目录规划纪律】
1. 六个一级目录必须保留其上述 DV 业务含义，不得重新解释或新增一级目录。
2. 二级目录应反映可复用的验证主题，同类测试点必须共享目录；禁止接近一条测试点创建一个目录。
3. 先理解完整测试意图和 Spec 合法范围，不得根据 raw_tag 中的“边界、交叉、乱序、响应”等单词猜分类。
4. 合法最小值、最大值、支持的参数组合属于正常功能；非法越界或不支持操作属于异常；只有多个合法极限叠加后仍处于支持域、罕见并发、资源/状态转换交互，或多个独立错误机制的优先级交互，才属于 corner。
5. category_id 必须稳定、简短、使用大写英文、数字和连字符，例如 FUNC-SRAM-READ、CORNER-RESET-INFLIGHT。
6. 只建立当前测试点实际需要的二级目录，不要求每个一级目录一定非空。
7. 二级目录的名称和描述必须能准确覆盖其成员测试点。紧凑不能牺牲语义：地址/4KB边界错误不得塞入“非法Size”，随机反压不得塞入“极限恢复”。
8. 为每个实际存在的独立行为轴准备可复用目录；可以合并同义测试点，但不能为了减少目录数而合并不同协议字段、不同地址规则或不同错误机制。
9. 不得为“合法起点但后续地址越界”建立 corner 目录，它仍是单一地址范围错误机制；可以为“同一请求同时命中两个独立错误机制并验证优先级”建立 corner 目录。

【严格输出格式】
只能输出符合以下 JSON Schema 的对象：
{json.dumps(schema_json, ensure_ascii=False, indent=2)}
"""
    user_prompt = f"""
【完整 Spec 全局事实】
{json.dumps(global_context, ensure_ascii=False, indent=2)}

【待规划目录的完整测试点】
{json.dumps(point_payload, ensure_ascii=False, indent=2)}
"""

    print(
        f"  正在规划六类二级目录: "
        f"基于 {len(indexed_testpoints)} 条完整测试点..."
    )
    taxonomy = request_validated_json(
        client,
        model_name,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        ClassificationTaxonomy,
        "分类目录",
        validator=validate_classification_taxonomy,
    )
    return taxonomy


def validate_classification_taxonomy(taxonomy: ClassificationTaxonomy) -> None:
    category_ids = [category.category_id for category in taxonomy.secondary_categories]
    duplicates = sorted(
        category_id
        for category_id in set(category_ids)
        if category_ids.count(category_id) > 1
    )
    invalid_ids = sorted(
        category_id
        for category_id in category_ids
        if not re.fullmatch(r"[A-Z0-9-]+", category_id)
    )
    duplicate_names = sorted(
        {
            f"{category.primary_category}/{category.name}"
            for category in taxonomy.secondary_categories
            if sum(
                1
                for other in taxonomy.secondary_categories
                if other.primary_category == category.primary_category
                and other.name == category.name
            )
            > 1
        }
    )

    errors = []
    if duplicates:
        errors.append(f"二级目录 ID 重复: {duplicates}")
    if invalid_ids:
        errors.append(f"二级目录 ID 非法: {invalid_ids}")
    if duplicate_names:
        errors.append(f"同一一级目录下二级目录重名: {duplicate_names}")
    if errors:
        raise ValueError("分类目录无效: " + "; ".join(errors))


def classify_testpoints(
    client,
    model_name: str,
    global_context: dict,
    indexed_testpoints: list[IndexedTestpoint],
    taxonomy: ClassificationTaxonomy,
    batch_size: int | None = None,
) -> TestpointClassificationResult:
    """Classify complete testpoints by intent instead of mapping free-form raw tags."""
    schema_json = TestpointClassificationResult.model_json_schema()
    taxonomy_payload = taxonomy.model_dump()
    system_prompt = f"""
你是资深数字 IC 验证架构师。请将每条完整测试点分配到给定的一级和二级目录。

【固定一级目录及业务定义】
{json.dumps(PRIMARY_CATEGORY_GUIDE, ensure_ascii=False, indent=2)}

【核心判定方法】
1. 先填写 legality：合法正常刺激为 legal_supported；Spec 明确定义应返回错误的关闭态访问、越界或不支持类型为 defined_error_condition；Spec/协议明确禁止但项目未定义处理方式的刺激为 unsupported_or_illegal；Spec 没有决定是否支持或采用哪种策略时为 spec_ambiguous。
2. 分类必须阅读 summary、details、依据反标和 source_chunk；raw_tag 只作为辅助，不能按标签关键词分类。
3. 单独验证合法最小值、最大值、所有支持 ID、支持的 size/length 组合，属于接口或功能，不属于 corner。
4. 明确不支持的参数、越界地址及 SLVERR/DECERR 处理属于异常。
5. verification_intent 与一级目录必须严格按以下映射：
{json.dumps(INTENT_TO_PRIMARY_CATEGORY, ensure_ascii=False, indent=2)}
6. corner_interaction 必须至少命中一个真实触发条件，并填写可核查证据：
{json.dumps(CORNER_TRIGGER_GUIDE, ensure_ascii=False, indent=2)}
   先看最终验证结果，不看刺激构造是否复杂：只验证一个越界、不支持字段或错误响应时必须归异常；只有资源/状态交互，或至少两个独立错误机制的优先级交互，才可归 corner。随机反压、普通背靠背流量、普通 non-blocking、包间独立性本身也不是 corner。
7. 合法最高地址和合法最大Burst长度仍是 normal_function；所有支持ID的返回匹配通常是 interface_contract；长时间反压后的恢复可为 corner_interaction；同地址读写资源冲突可为 corner_interaction。
8. Spec 明确支持的 AW/W 乱序到达等行为属于正常接口或功能，不得因“乱序”二字归入异常。
9. 普通 B/R OKAY 响应是接口或功能的一部分；只有测试目的本身是中断、状态、告警或可观察上报机制时才归上报。
10. 非 corner 的 corner_triggers 必须为空且 corner_evidence 必须为空；corner 的 legality 只能是 legal_supported 或 spec_ambiguous，不能把已定义错误或非法刺激包装成 corner。
11. 每个 testpoint_id 必须且只能出现一次，secondary_category_id 必须来自给定目录，并与 primary_category 一致。
12. 输入测试点已经经过独立原子性审查。分类阶段只负责目录归属，不得重新拆点；needs_split 必须为 false，split_reason 必须为空字符串。
13. 逐字检查二级目录 name 和 description 是否真正覆盖当前测试点的行为轴。仅仅一级目录相同、都涉及AXI或都包含“临界”二字，不代表二级目录匹配。
14. 如果没有准确二级目录，category_fit=false、secondary_category_id填空字符串，并在 proposed_secondary_category 提议一个可复用的新目录；不要把复位转换塞进同拍valid-ready握手，也不要把地址边界塞进Size错误。
15. 如果现有目录准确匹配，category_fit=true、category_fit_reason说明对应关系，proposed_secondary_category必须为null。
16. outcome_focus 必须描述最终要确认的结果，并与 verification_intent 一致：接口/功能使用 normal_supported_behavior；异常使用 single_error_handling；场景使用 workflow_behavior；上报使用 reporting_behavior；corner 只能使用 state_or_resource_interaction 或 multiple_error_interaction。
17. single_error_handling 的 error_mechanisms 必须恰好描述一个主要错误机制。multiple_error_interaction 必须列出至少两个相互独立的错误机制并使用同名 Corner 触发条件。其他结果域通常留空。
18. multi_constraint_extreme 只适用于组合后仍合法的多极限刺激。合法起点的 Burst 后续 beat 越界、合法参数组合后触发单一地址错误，最终仍是 single_error_handling，不是 corner。

【严格输出格式】
只能输出符合以下 JSON Schema 的对象：
{json.dumps(schema_json, ensure_ascii=False, indent=2)}
"""
    effective_batch_size = batch_size or int(
        os.getenv("DV_CLASSIFICATION_BATCH_SIZE", "40")
    )
    if effective_batch_size <= 0:
        raise ValueError("DV_CLASSIFICATION_BATCH_SIZE 必须大于 0")

    all_assignments = []
    batches = [
        indexed_testpoints[index:index + effective_batch_size]
        for index in range(0, len(indexed_testpoints), effective_batch_size)
    ]
    for batch_index, batch in enumerate(batches, start=1):
        point_payload = build_testpoint_payload(batch)
        user_prompt = f"""
【完整 Spec 全局事实】
{json.dumps(global_context, ensure_ascii=False, indent=2)}

【允许使用的分类目录】
{json.dumps(taxonomy_payload, ensure_ascii=False, indent=2)}

【本批待分类的完整测试点】
{json.dumps(point_payload, ensure_ascii=False, indent=2)}
"""

        print(
            f"  正在按完整测试意图分类: "
            f"批次 {batch_index}/{len(batches)}，{len(batch)} 条..."
        )
        batch_result = request_validated_json(
            client,
            model_name,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            TestpointClassificationResult,
            f"测试点分类批次 {batch_index}",
            validator=lambda parsed, current_batch=batch: validate_classification_result(
                current_batch,
                taxonomy,
                parsed,
            ),
        )
        all_assignments.extend(batch_result.assignments)

    result = TestpointClassificationResult(assignments=all_assignments)
    validate_classification_result(indexed_testpoints, taxonomy, result)
    return result


def review_testpoint_atomicity(
    client,
    model_name: str,
    global_context: dict,
    indexed_testpoints: list[IndexedTestpoint],
    batch_size: int | None = None,
) -> TestpointAtomicityReview:
    """Split only genuinely ambiguous mixed-intent points before classification."""
    if not indexed_testpoints:
        return TestpointAtomicityReview(splits=[], kept_testpoints=[])

    schema_json = TestpointAtomicityReview.model_json_schema()
    system_prompt = f"""
你是资深数字 IC 验证工程师。请在分类前审查测试点是否具有清晰、单一的验证意义。

【固定一级目录及业务定义】
{json.dumps(PRIMARY_CATEGORY_GUIDE, ensure_ascii=False, indent=2)}

【原子性审查边界】
1. 只有当同一条测试点混合了无法用一个明确预期解释的验证意图时才拆分。典型情况是同时验证合法支持行为与非法/不支持行为，或者同时要求互不相同的成功与错误响应。
2. 不要拆分同一行为的参数遍历、合法最小值与最大值、所有支持的 ID、多个合法 size/length 组合，前提是它们共享同一验证目的和预期。
3. 不要拆分同一事务需要共同观察的数据、响应、握手和状态；这些观察项共同定义一个有意义的行为。
4. 不要拆分刻意叠加的 corner 条件，例如最大 outstanding、持续反压与复位的交互。多约束组合本身就是该 corner 测试的验证目的。
5. 不要因为 summary/details 较长、包含“以及/同时/边界/最大/交叉”等字样，或可能覆盖多个 coverpoint 就机械拆分。
6. 仅在保持原文会造成分类归属含糊或通过条件相互冲突时拆分。拿不准时保留原测试点，不要过拆。
7. 如果 is_spec_ambiguous=true 且原文只是列出“支持时怎样、不支持时怎样”或多个待设计选择，不要把这些未知分支拆成看似同时必做的条件测试；拆分不能替代需求澄清。
8. 上一条不妨碍拆分客观可区分的合法与非法刺激。例如合法 size/length 正常完成和超范围组合报错仍应拆开，即使支持边界、具体错误码或部分实现策略待澄清。替代测试点保留这些歧义，不得凭空补需求。
9. 本批每个 testpoint_id 必须且只能出现一次：必须拆分的放入 splits，保留原样的放入 kept_testpoints。禁止静默省略任何ID。
10. replacement 必须完整保留原有覆盖意义和准确的 Spec/Skill 反标，使用自然、明确、能指导 DV review 的语言，不要求固定句式。
11. separable_stimulus_classes 表示能否按客观输入条件划分不同刺激域。支持/不支持、范围内/范围外等即使具体边界待澄清也属于可分；同一个跨4KB请求究竟报错、切分还是由上游禁止，属于不可分的设计选择。
12. 每个 split 必须同时满足：normal_completion_present=true、error_response_present=true、single_invariant_or_scenario=false、separable_stimulus_classes=true。unresolved_design_alternatives 不能作为漏拆豁免；若刺激域可分，拆分后的每条测试点继续保留对应歧义。
    kept_testpoints 如果也满足这四项，说明发生漏拆，必须改放入 splits。
13. sram_en/sram_we 等信号“访问时拉高、空闲/复位/错误时拉低”共同定义一个门控不变量，single_invariant_or_scenario 应为 true，不得拆分。
14. “复位期间保持安全输出，释放后继续处理请求”等刻意跨阶段场景，single_invariant_or_scenario 应为 true，不得按阶段拆分。

【严格输出格式】
只能输出符合以下 JSON Schema 的对象：
{json.dumps(schema_json, ensure_ascii=False, indent=2)}
"""
    effective_batch_size = batch_size or int(
        os.getenv("DV_ATOMICITY_BATCH_SIZE", "40")
    )
    if effective_batch_size <= 0:
        raise ValueError("DV_ATOMICITY_BATCH_SIZE 必须大于 0")

    batches = [
        indexed_testpoints[index:index + effective_batch_size]
        for index in range(0, len(indexed_testpoints), effective_batch_size)
    ]
    all_splits = []
    all_kept_testpoints = []
    for batch_index, batch in enumerate(batches, start=1):
        user_prompt = f"""
【完整 Spec 全局事实】
{json.dumps(global_context, ensure_ascii=False, indent=2)}

【本批待审查的完整测试点】
{json.dumps(build_testpoint_payload(batch), ensure_ascii=False, indent=2)}
"""
        print(
            "  正在审查测试点原子性: "
            f"批次 {batch_index}/{len(batches)}，{len(batch)} 条..."
        )
        batch_review = request_validated_json(
            client,
            model_name,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            TestpointAtomicityReview,
            f"原子性审查批次 {batch_index}",
            validator=lambda parsed, current_batch=batch: validate_atomicity_review(
                {point.testpoint_id for point in current_batch},
                parsed,
            ),
        )
        all_splits.extend(batch_review.splits)
        all_kept_testpoints.extend(batch_review.kept_testpoints)

    review = TestpointAtomicityReview(
        splits=all_splits,
        kept_testpoints=all_kept_testpoints,
    )
    validate_atomicity_review(
        {point.testpoint_id for point in indexed_testpoints},
        review,
    )
    return review


def validate_classification_result(
    indexed_testpoints: list[IndexedTestpoint],
    taxonomy: ClassificationTaxonomy,
    result: TestpointClassificationResult,
) -> None:
    expected_ids = {point.testpoint_id for point in indexed_testpoints}
    assignment_ids = [assignment.testpoint_id for assignment in result.assignments]
    assignment_set = set(assignment_ids)
    category_by_id = {
        category.category_id: category
        for category in taxonomy.secondary_categories
    }

    duplicates = sorted(
        testpoint_id
        for testpoint_id in assignment_set
        if assignment_ids.count(testpoint_id) > 1
    )
    missing = sorted(expected_ids - assignment_set)
    unknown = sorted(assignment_set - expected_ids)
    unknown_categories = sorted(
        {
            assignment.secondary_category_id
            for assignment in result.assignments
            if assignment.category_fit
            if assignment.secondary_category_id not in category_by_id
        }
    )
    mismatched_categories = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if assignment.category_fit
        and assignment.secondary_category_id in category_by_id
        and category_by_id[assignment.secondary_category_id].primary_category
        != assignment.primary_category
    )
    category_fit_contract_errors = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if not assignment.category_fit_reason.strip()
        or (
            assignment.category_fit
            and (
                not assignment.secondary_category_id
                or assignment.proposed_secondary_category is not None
            )
        )
        or (
            not assignment.category_fit
            and (
                assignment.secondary_category_id != ""
                or assignment.proposed_secondary_category is None
            )
        )
        or (
            assignment.proposed_secondary_category is not None
            and (
                assignment.proposed_secondary_category.primary_category
                != assignment.primary_category
                or not re.fullmatch(
                    r"[A-Z0-9-]+",
                    assignment.proposed_secondary_category.category_id,
                )
            )
        )
    )
    intent_mismatches = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if INTENT_TO_PRIMARY_CATEGORY.get(assignment.verification_intent)
        != assignment.primary_category
    )
    outcome_focus_mismatches = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if assignment.verification_intent
        not in OUTCOME_FOCUS_TO_INTENTS.get(assignment.outcome_focus, set())
    )
    invalid_corner_contracts = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if (
            assignment.verification_intent == "corner_interaction"
            and (
                not assignment.corner_triggers
                or not assignment.corner_evidence.strip()
                or assignment.legality
                in {"defined_error_condition", "unsupported_or_illegal"}
                or (
                    "multi_constraint_extreme" in assignment.corner_triggers
                    and assignment.legality != "legal_supported"
                )
                or (
                    assignment.outcome_focus == "multiple_error_interaction"
                    and "multiple_error_interaction"
                    not in assignment.corner_triggers
                )
                or (
                    assignment.outcome_focus
                    == "state_or_resource_interaction"
                    and "multiple_error_interaction"
                    in assignment.corner_triggers
                )
            )
        )
        or (
            assignment.verification_intent != "corner_interaction"
            and (
                assignment.corner_triggers
                or assignment.corner_evidence.strip()
            )
        )
    )
    invalid_error_mechanism_contracts = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if (
            assignment.outcome_focus == "single_error_handling"
            and len(
                {
                    mechanism.strip()
                    for mechanism in assignment.error_mechanisms
                    if mechanism.strip()
                }
            )
            != 1
        )
        or (
            assignment.outcome_focus == "multiple_error_interaction"
            and len(
                {
                    mechanism.strip()
                    for mechanism in assignment.error_mechanisms
                    if mechanism.strip()
                }
            )
            < 2
        )
        or (
            assignment.outcome_focus
            in {
                "normal_supported_behavior",
                "reporting_behavior",
                "state_or_resource_interaction",
            }
            and assignment.error_mechanisms
        )
    )
    legality_intent_conflicts = sorted(
        assignment.testpoint_id
        for assignment in result.assignments
        if (
            assignment.legality
            in {"defined_error_condition", "unsupported_or_illegal"}
            and assignment.verification_intent
            in {"interface_contract", "normal_function"}
        )
        or (
            assignment.legality == "legal_supported"
            and assignment.verification_intent == "error_handling"
        )
    )

    errors = []
    if duplicates:
        errors.append(f"测试点重复分类: {duplicates}")
    if missing:
        errors.append(f"测试点漏分类: {missing}")
    if unknown:
        errors.append(f"出现未知测试点 ID: {unknown}")
    if unknown_categories:
        errors.append(f"使用未知二级目录: {unknown_categories}")
    if mismatched_categories:
        errors.append(f"一级/二级目录不匹配: {mismatched_categories}")
    if category_fit_contract_errors:
        errors.append(f"二级目录匹配声明无效: {category_fit_contract_errors}")
    if intent_mismatches:
        errors.append(f"主验证意图与一级目录不匹配: {intent_mismatches}")
    if outcome_focus_mismatches:
        errors.append(f"结果关注域与主验证意图不匹配: {outcome_focus_mismatches}")
    if invalid_corner_contracts:
        errors.append(f"corner 触发条件或合法性无效: {invalid_corner_contracts}")
    if invalid_error_mechanism_contracts:
        errors.append(f"错误机制声明无效: {invalid_error_mechanism_contracts}")
    if legality_intent_conflicts:
        errors.append(f"合法性与主验证意图冲突: {legality_intent_conflicts}")
    if errors:
        raise ValueError("测试点分类结果无效: " + "; ".join(errors))


def _extend_taxonomy_with_proposals(
    taxonomy: ClassificationTaxonomy,
    assignments: list,
) -> ClassificationTaxonomy:
    categories = list(taxonomy.secondary_categories)
    ids = {category.category_id for category in categories}
    names = {
        (category.primary_category, category.name): category.category_id
        for category in categories
    }

    for assignment in assignments:
        proposal = assignment.proposed_secondary_category
        if proposal is None:
            continue
        name_key = (proposal.primary_category, proposal.name)
        if name_key in names:
            continue

        candidate_id = proposal.category_id
        suffix = 2
        while candidate_id in ids:
            candidate_id = f"{proposal.category_id}-{suffix}"
            suffix += 1
        category = proposal.model_copy(update={"category_id": candidate_id})
        categories.append(category)
        ids.add(candidate_id)
        names[name_key] = candidate_id

    expanded = ClassificationTaxonomy(secondary_categories=categories)
    validate_classification_taxonomy(expanded)
    return expanded


def resolve_category_gaps(
    client,
    model_name: str,
    global_context: dict,
    indexed_testpoints: list[IndexedTestpoint],
    taxonomy: ClassificationTaxonomy,
    classification: TestpointClassificationResult,
) -> tuple[ClassificationTaxonomy, TestpointClassificationResult]:
    """Expand missing secondary topics and reclassify only affected points."""
    max_rounds = int(os.getenv("DV_CATEGORY_REPAIR_ROUNDS", "2"))
    if max_rounds < 0:
        raise ValueError("DV_CATEGORY_REPAIR_ROUNDS 不能小于 0")

    current_taxonomy = taxonomy
    current_result = classification
    point_by_id = {point.testpoint_id: point for point in indexed_testpoints}

    for round_index in range(max_rounds + 1):
        gaps = [
            assignment
            for assignment in current_result.assignments
            if not assignment.category_fit
        ]
        if not gaps:
            validate_classification_result(
                indexed_testpoints,
                current_taxonomy,
                current_result,
            )
            return current_taxonomy, current_result
        if round_index >= max_rounds:
            gap_ids = [assignment.testpoint_id for assignment in gaps]
            raise ValueError(f"二级目录自动扩展后仍不匹配: {gap_ids}")

        print(
            f"  检测到 {len(gaps)} 条测试点缺少准确二级目录，"
            f"正在扩展目录并重分类 ({round_index + 1}/{max_rounds})..."
        )
        current_taxonomy = _extend_taxonomy_with_proposals(
            current_taxonomy,
            gaps,
        )
        gap_points = [point_by_id[gap.testpoint_id] for gap in gaps]
        repaired = classify_testpoints(
            client,
            model_name,
            global_context,
            gap_points,
            current_taxonomy,
            batch_size=len(gap_points),
        )
        repaired_by_id = {
            assignment.testpoint_id: assignment
            for assignment in repaired.assignments
        }
        current_result = TestpointClassificationResult(
            assignments=[
                repaired_by_id.get(assignment.testpoint_id, assignment)
                for assignment in current_result.assignments
            ]
        )

    raise AssertionError("unreachable")


def split_mixed_testpoints(
    client,
    model_name: str,
    global_context: dict,
    indexed_testpoints: list[IndexedTestpoint],
    classification: TestpointClassificationResult,
) -> TestpointAtomicityReview:
    """Compatibility wrapper for reviewing classifier-nominated points."""
    mixed_ids = {
        assignment.testpoint_id
        for assignment in classification.assignments
        if assignment.needs_split
    }
    if not mixed_ids:
        return TestpointAtomicityReview(splits=[], kept_testpoints=[])

    mixed_points = [
        point
        for point in indexed_testpoints
        if point.testpoint_id in mixed_ids
    ]
    return review_testpoint_atomicity(
        client,
        model_name,
        global_context,
        mixed_points,
        batch_size=len(mixed_points),
    )


def validate_atomicity_review(
    expected_ids: set[str],
    review: TestpointAtomicityReview,
) -> None:
    split_ids = [split.original_testpoint_id for split in review.splits]
    kept_ids = [decision.testpoint_id for decision in review.kept_testpoints]
    reviewed_ids = split_ids + kept_ids
    reviewed_set = set(reviewed_ids)
    duplicates = sorted(
        testpoint_id
        for testpoint_id in reviewed_set
        if reviewed_ids.count(testpoint_id) > 1
    )
    missing = sorted(expected_ids - reviewed_set)
    unknown = sorted(reviewed_set - expected_ids)
    insufficient = sorted(
        split.original_testpoint_id
        for split in review.splits
        if len(split.replacements) < 2
    )
    ineligible = sorted(
        split.original_testpoint_id
        for split in review.splits
        if (
            not split.normal_completion_present
            or not split.error_response_present
            or split.single_invariant_or_scenario
            or not split.separable_stimulus_classes
        )
    )
    missed_eligible = sorted(
        decision.testpoint_id
        for decision in review.kept_testpoints
        if (
            decision.normal_completion_present
            and decision.error_response_present
            and not decision.single_invariant_or_scenario
            and decision.separable_stimulus_classes
        )
    )
    empty_keep_reasons = sorted(
        decision.testpoint_id
        for decision in review.kept_testpoints
        if not decision.rationale.strip()
    )

    errors = []
    if duplicates:
        errors.append(f"测试点重复出现在原子性台账: {duplicates}")
    if missing:
        errors.append(f"测试点未进入原子性台账: {missing}")
    if unknown:
        errors.append(f"原子性台账出现未知 ID: {unknown}")
    if insufficient:
        errors.append(f"拆分结果不足两条: {insufficient}")
    if ineligible:
        errors.append(f"不满足正常完成/错误响应拆分资格: {ineligible}")
    if missed_eligible:
        errors.append(f"满足拆分资格但被错误保留: {missed_eligible}")
    if empty_keep_reasons:
        errors.append(f"保留决定缺少依据: {empty_keep_reasons}")
    if errors:
        raise ValueError("测试点原子性修正无效: " + "; ".join(errors))


def apply_testpoint_splits(
    indexed_testpoints: list[IndexedTestpoint],
    review: TestpointAtomicityReview,
) -> list[IndexedTestpoint]:
    split_by_id = {
        split.original_testpoint_id: split
        for split in review.splits
    }
    output = []
    for indexed in indexed_testpoints:
        split = split_by_id.get(indexed.testpoint_id)
        if not split:
            output.append(indexed)
            continue
        for replacement_index, replacement in enumerate(split.replacements, start=1):
            output.append(
                IndexedTestpoint(
                    testpoint_id=f"{indexed.testpoint_id}-S{replacement_index}",
                    source_chunk=indexed.source_chunk,
                    testpoint=replacement,
                )
            )
    return output


def build_testpoint_tree(
    indexed_testpoints: list[IndexedTestpoint],
    taxonomy: ClassificationTaxonomy,
    result: TestpointClassificationResult,
) -> dict:
    """Build the final tree from validated per-testpoint assignments."""
    validate_classification_result(indexed_testpoints, taxonomy, result)
    assignment_by_id = {
        assignment.testpoint_id: assignment
        for assignment in result.assignments
    }

    used_category_ids = {
        assignment.secondary_category_id
        for assignment in result.assignments
    }
    secondary_labels = {}
    counters = defaultdict(int)
    ordered_categories = sorted(
        (
            category
            for category in taxonomy.secondary_categories
            if category.category_id in used_category_ids
        ),
        key=lambda category: (
            int(category.primary_category.split(".", 1)[0]),
            category.category_id,
        ),
    )
    for category in ordered_categories:
        counters[category.primary_category] += 1
        primary_number = category.primary_category.split(".", 1)[0]
        secondary_labels[category.category_id] = (
            f"{primary_number}.{counters[category.primary_category]} {category.name}"
        )

    tree = defaultdict(lambda: defaultdict(list))
    for indexed in indexed_testpoints:
        assignment = assignment_by_id[indexed.testpoint_id]
        secondary_label = secondary_labels[assignment.secondary_category_id]
        tree[assignment.primary_category][secondary_label].append(indexed)

    return {
        primary: dict(secondaries)
        for primary, secondaries in tree.items()
    }
