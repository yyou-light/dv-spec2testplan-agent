import json
import re
from schemas import TagMapping
from collections import defaultdict


# =====================================================================
# [Step 5] 后置标签聚合与建树层 (The Clustering LLM)
# =====================================================================
def generate_tag_mapping(client, model_name: str, unique_tags: list[str]) -> TagMapping:
    """
    将去重后的 raw_tag 列表发给大模型，要求其映射到标准的六大基石分类树中。
    """
    schema_json = TagMapping.model_json_schema()
    
    system_prompt = f"""
    你是一个资深的数字IC验证架构师。
    你的任务是将零散的测试点特征标签 (raw_tag) 进行同义词合并，并为它们分配标准的二级分类树路径。

    【验证规划的六大基石分类】
    1. 接口类 (Interface)
    2. 功能类 (Function)
    3. 场景类 (Scenario)
    4. 异常类 (Exception)
    5. 上报类 (Report)
    6. corner类 (Corner)

    【严格输出格式】
    你必须且只能输出严格的 JSON 格式。结构必须符合以下 JSON Schema：
    {json.dumps(schema_json, ensure_ascii=False, indent=2)}

    【映射规则说明 (极其重要)】
    1. 你生成的字典 Value 必须严格符合格式："X.大分类-X.Y 二级分类"。
    2. 例如，如果输入的 raw_tag 是 "AXI读越界"，你可以将其映射为 "4.异常类-4.1 AXI总线异常"。
    3. 如果输入的 raw_tag 是 "SRAM握手" 和 "SRAM_REQ"，你可以将它们合并，都映射为 "1.接口类-1.2 SRAM控制接口"。
    4. 确保输入的每一个 tag 都必须出现在字典的 Key 中，不能遗漏！
    """
    
    user_prompt = f"""
    【需要你进行分类映射的原始标签列表】
    {json.dumps(unique_tags, ensure_ascii=False)}
    """
    
    print(f"  🧠 大脑正在进行降维打击：将 {len(unique_tags)} 个零散标签聚合成标准目录树...")
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    
    response_content = response.choices[0].message.content
    try:
        mapping_obj = TagMapping.model_validate_json(response_content)
        return mapping_obj
    except Exception as e:
        print(f"  ❌ 标签映射格式校验失败: {e}")
        return TagMapping(mapping_dict={})

# =====================================================================
# 纯 Python 逻辑：根据大模型给的字典，把散落的测试点装进树状结构
# =====================================================================
def build_testpoint_tree(testpoints: list, mapping_dict: dict) -> dict:
    """
    根据大模型生成的映射字典，将打平的测试点组装成多级树状结构。
    具备极强的格式容错与降级处理能力。
    """
    tree = defaultdict(lambda: defaultdict(list))
    
    for tp in testpoints:
        # 获取大模型给这个标签的归类结果
        mapped_value = mapping_dict.get(tp.raw_tag)
        
        primary = "9.未分类"
        secondary = "9.9 默认子类"
        
        if isinstance(mapped_value, list) and len(mapped_value) >= 2:
            # 正常情况：大模型乖乖返回了 List
            primary = str(mapped_value[0]).strip()
            secondary = str(mapped_value[1]).strip()
            
        elif isinstance(mapped_value, str):
            # 🌟 容错魔法：大模型偷懒返回了字符串 (如 "2.功能类-2.2 AXI转换")
            # 自动根据常见的连接符（-、>、:、|）将其切开
            parts = re.split(r'[-_>|:]', mapped_value, maxsplit=1)
            if len(parts) == 2:
                primary = parts[0].strip()
                secondary = parts[1].strip()
            else:
                # 实在切不开，就全塞进去
                primary = "8.格式降级类"
                secondary = mapped_value.strip()
                
        elif isinstance(mapped_value, dict):
            # 容错：大模型返回了嵌套字典 {"2.功能类": "2.2 AXI转换"}
            keys = list(mapped_value.keys())
            if keys:
                primary = keys[0]
                secondary = str(mapped_value[primary])
                
        # 挂载到树上
        tree[primary][secondary].append(tp)
        
    return dict(tree)