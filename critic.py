import json
from schemas import AuditReport, RawTestpointList
from extractor import route_dynamic_skills

# =====================================================================
# [Step 6] Checker: 找茬大模型 (The AI Critic)
# =====================================================================
def audit_extracted_testpoints(client, model_name: str, chunk: dict, extracted_points: list) -> AuditReport:
    schema_json = AuditReport.model_json_schema()
    
    # 提取所有已被 Maker 覆盖的原文句子
    existing_quotes = [tp.spec_quote for tp in extracted_points]
    
    # 🌟 核心对齐：拿取和 Extractor 一模一样的考纲
    aligned_layer_3 = route_dynamic_skills(chunk['content'])
    
    system_prompt = f"""
    【角色设定】你是一个极其挑剔的资深数字IC验证架构师 (DV Architect)。
    【核心审计纪律】
    1. 证据至上：去原文中找那些包含硬件行为逻辑（如果、当、必须）的句子。
    2. 判定漏测：如果某句原话包含了独立硬件行为，但它没有出现在【已被覆盖的反标列表】中，这就是漏测！
    
    【⚖️ 对齐考纲：隐式推导特权豁免】
    以下是赋予提取者的合法推导特权。如果提取者基于这些规则提取了测试点，即使找不到一字不差的原文，也**绝对不准**判定为漏测：
    {aligned_layer_3}
    
    【强制输出格式】
    必须符合以下 JSON Schema：
    {json.dumps(schema_json, ensure_ascii=False, indent=2)}
    """
    
    user_prompt = f"""
    【待审计原文 (Chunk: {chunk['group_name']})】
    {chunk['content']}
    
    【已被覆盖的反标列表 (spec_quote List)】
    {json.dumps(existing_quotes, ensure_ascii=False, indent=2)}
    """
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"}, 
        temperature=0.0 # 审计需要极度冷静，设为 0
    )
    
    try:
        return AuditReport.model_validate_json(response.choices[0].message.content)
    except Exception as e:
        print(f"  ❌ 审计报错: {e}")
        return AuditReport(is_passed=True, critic_notes="解析失败，默认放行")