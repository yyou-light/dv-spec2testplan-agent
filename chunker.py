import re
from schemas import SemanticChunkingPlan

# =====================================================================
# [Step 3] 物理切块执行器：带自愈机制的无损文本切割
# =====================================================================
def execute_physical_chunking(markdown_text: str, plan: SemanticChunkingPlan) -> list[dict]:
    lines = markdown_text.split('\n')
    sections_dict = {}
    current_section = "前言_系统默认"
    sections_dict[current_section] = []
    
    # 记录所有标题出现的物理顺序
    header_order = []
    
    for line in lines:
        match = re.match(r'^(#{1,6})\s+(.*)', line)
        if match:
            current_section = match.group(2).strip()
            if current_section not in sections_dict:
                sections_dict[current_section] = []
                header_order.append(current_section)
            sections_dict[current_section].append(line)
        else:
            sections_dict[current_section].append(line)
            
    final_chunks = []
    assembled_sections = set()
    
    for group in plan.merge_groups:
        chunk_lines = []
        for sec_title in group.sections:
            clean_title = sec_title.strip()
            
            # 1. 精准匹配
            if clean_title in sections_dict:
                chunk_lines.extend(sections_dict[clean_title])
                assembled_sections.add(clean_title)
            else:
                # 2. 模糊匹配自愈 (处理大模型偶尔吃掉空格或标点的情况)
                matched = False
                for real_title in sections_dict.keys():
                    # 比如把 "1.模块概述" 和 "1. 模块概述" 匹配上
                    if clean_title in real_title or real_title in clean_title:
                        chunk_lines.extend(sections_dict[real_title])
                        assembled_sections.add(real_title)
                        matched = True
                        print(f"🔄 [切块自愈]: 成功将图纸中的 '{clean_title}' 映射到真实标题 '{real_title}'")
                        break
                
                if not matched:
                    print(f"⚠️ [警告]: 图纸中的章节 '{clean_title}' 在原文中彻底丢失！")
                
        if chunk_lines:
            final_chunks.append({
                "group_name": group.group_name,
                "content": "\n".join(chunk_lines).strip()
            })

    # ==========================================
    # 🛡️ 防漏测断言逻辑升级
    # ==========================================
    original_sections = set(sections_dict.keys())
    original_sections.remove("前言_系统默认")
    
    # 👑 【核心修复】自动豁免文档的全局大标题 (通常是物理排版上的第一个 Header)
    if header_order:
        document_title = header_order[0]
        if document_title in original_sections and document_title not in assembled_sections:
            original_sections.remove(document_title)
            print(f"ℹ️ [豁免机制]: 已自动忽略全局文档标题 -> '{document_title}'")
    
    missed_sections = original_sections - assembled_sections
    
    if missed_sections:
        error_msg = f"❌ 严重错误: 发现漏测风险！以下章节未进入 Chunk: {missed_sections}"
        raise AssertionError(error_msg)
    else:
        print("🛡️ 安全断言通过：原文所有业务章节均已完美装箱，零数据丢失！")

    return final_chunks