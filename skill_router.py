import json

from extractor import (
    detect_skill_names,
    get_skill_rule_catalog,
    render_selected_skill_rules,
)
from schemas import SkillRoutingPlan


def build_semantic_skill_routing_plan(
    client,
    model_name: str,
    document_text: str,
    chunks: list[dict],
    global_context: dict,
) -> SkillRoutingPlan:
    """Assign every candidate DV rule to the most relevant chunk using full-document context."""
    skill_names = detect_skill_names(document_text)
    rule_catalog = get_skill_rule_catalog(skill_names)
    if not rule_catalog:
        return SkillRoutingPlan(applications=[])

    schema_json = SkillRoutingPlan.model_json_schema()
    chunk_payload = [
        {
            "group_name": chunk["group_name"],
            "content": chunk["content"],
        }
        for chunk in chunks
    ]
    rule_payload = [
        {
            "rule_ref": rule_ref,
            "kind": rule["kind"],
            "rule": rule["text"],
        }
        for rule_ref, rule in rule_catalog.items()
    ]

    system_prompt = f"""
你是数字 IC 验证规划师。你的任务不是生成测试点，而是为完整 Spec 制定 Skill 规则应用计划。

【核心目标】
1. 候选 Skill 已由确定性程序根据完整文档筛出。只要协议或接口被完整 Spec 确认，候选规则就是 DV 工作流需要考虑的经验覆盖，不要求 Spec 逐字写出。
2. 每条候选规则必须且只能在 applications 中出现一次，并至少分配给一个最适合落实它的 Chunk。
3. 默认只分配给一个 Chunk。只有确实存在不同验证对象时才可分配多个 Chunk，并在 coverage_targets 中说明差异。
4. 不要因为当前某个 Chunk 没出现协议关键词就丢弃规则；判断必须基于完整全局事实和全部 Chunk。
5. 不要把同一条规则机械分配给每个 Chunk。目标是保留完整 DV 经验覆盖，同时避免跨 Chunk 同义重复。
6. target_chunks 必须逐字使用给定的 group_name。

【严格输出格式】
只能输出符合以下 JSON Schema 的对象：
{json.dumps(schema_json, ensure_ascii=False, indent=2)}
"""
    user_prompt = f"""
【完整 Spec 全局事实】
{json.dumps(global_context, ensure_ascii=False, indent=2)}

【候选 Skill 规则，必须全部分配】
{json.dumps(rule_payload, ensure_ascii=False, indent=2)}

【可分配的 Chunk】
{json.dumps(chunk_payload, ensure_ascii=False, indent=2)}
"""

    print(
        f"🧭 正在进行全局 Skill 路由: "
        f"命中 {len(skill_names)} 个 Skill，规划 {len(rule_catalog)} 条规则..."
    )
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
        max_tokens=8192,
    )
    plan = SkillRoutingPlan.model_validate_json(response.choices[0].message.content)
    validate_skill_routing_plan(plan, rule_catalog, chunks)
    return plan


def validate_skill_routing_plan(
    plan: SkillRoutingPlan,
    rule_catalog: dict[str, dict],
    chunks: list[dict],
) -> None:
    expected_rules = set(rule_catalog)
    chunk_names = {chunk["group_name"] for chunk in chunks}
    routed_rules = [application.rule_ref for application in plan.applications]
    routed_set = set(routed_rules)

    duplicate_rules = sorted(
        rule_ref
        for rule_ref in routed_set
        if routed_rules.count(rule_ref) > 1
    )
    unknown_rules = sorted(routed_set - expected_rules)
    missing_rules = sorted(expected_rules - routed_set)
    invalid_targets = sorted(
        {
            target
            for application in plan.applications
            for target in application.target_chunks
            if target not in chunk_names
        }
    )
    empty_targets = sorted(
        application.rule_ref
        for application in plan.applications
        if not application.target_chunks
    )

    errors = []
    if duplicate_rules:
        errors.append(f"规则重复: {duplicate_rules}")
    if unknown_rules:
        errors.append(f"未知规则: {unknown_rules}")
    if missing_rules:
        errors.append(f"规则漏分配: {missing_rules}")
    if invalid_targets:
        errors.append(f"未知 Chunk: {invalid_targets}")
    if empty_targets:
        errors.append(f"未指定目标 Chunk: {empty_targets}")
    if errors:
        raise ValueError("Skill 全局路由结果无效: " + "; ".join(errors))


def build_chunk_skill_prompts(plan: SkillRoutingPlan) -> dict[str, str]:
    """Render per-chunk prompts from the validated global routing plan."""
    catalog = get_skill_rule_catalog()
    rules_by_chunk: dict[str, list[dict]] = {}
    for application in plan.applications:
        rule = catalog[application.rule_ref]
        for chunk_name in dict.fromkeys(application.target_chunks):
            routed_rule = dict(rule)
            routed_rule["routing_rationale"] = application.rationale
            routed_rule["coverage_targets"] = application.coverage_targets
            rules_by_chunk.setdefault(chunk_name, []).append(routed_rule)

    return {
        chunk_name: render_selected_skill_rules(rules)
        for chunk_name, rules in rules_by_chunk.items()
    }
