import json
import os
import re
from schemas import RawTestpointList

# =====================================================================
# 🌟 [全局配置] 动态加载外部 Prompt 配置文件的路径定位
# =====================================================================
PROMPT_DIR = os.path.join(os.path.dirname(__file__), 'prompts')
SKILLS_DIR = os.path.join(PROMPT_DIR, 'skills')

def _load_prompt_file(filename: str) -> str:
    """加载基础的系统级 Prompt 文件"""
    filepath = os.path.join(PROMPT_DIR, filename)
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        print(f"⚠️ 找不到基础配置文件: {filepath}")
        return ""

def _build_skill_library() -> dict:
    """
    自动遍历 skills 文件夹，将所有 .md 技能文档解析为规范化的技能字典。
    支持三段式：# keywords, # explicit_rules, # implicit_rules
    """
    skill_lib = {}
    if not os.path.exists(SKILLS_DIR):
        print(f"⚠️ 找不到技能模块文件夹: {SKILLS_DIR}，请确保目录结构正确。")
        return skill_lib
        
    for filename in os.listdir(SKILLS_DIR):
        if filename.endswith(".md"):
            skill_name = filename.replace(".md", "").upper()
            filepath = os.path.join(SKILLS_DIR, filename)
            
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # 🌟 使用正则优雅地切分三段落 (兼容大小写和不同系统的换行符)
                kw_match = re.search(r'#\s*keywords\s*(.*?)(?=#\s*explicit_rules|#\s*implicit_rules|$)', content, re.DOTALL | re.IGNORECASE)
                exp_match = re.search(r'#\s*explicit_rules\s*(.*?)(?=#\s*implicit_rules|$)', content, re.DOTALL | re.IGNORECASE)
                imp_match = re.search(r'#\s*implicit_rules\s*(.*?)(?=$)', content, re.DOTALL | re.IGNORECASE)
                
                if kw_match:
                    # 把中文逗号、顿号、换行都替换成英文逗号，然后拆分成列表
                    kw_text = kw_match.group(1).replace('，', ',').replace('、', ',').replace('\n', ',')
                    keywords = [k.strip() for k in kw_text.split(',') if k.strip()]
                    
                    skill_lib[skill_name] = {
                        "keywords": keywords,
                        "explicit_rules": exp_match.group(1).strip() if exp_match else "",
                        "implicit_rules": imp_match.group(1).strip() if imp_match else ""
                    }
                else:
                    print(f"⚠️ [警告] 技能文件 '{filename}' 缺少 '# keywords' 标题，已跳过。")
                    
            except Exception as e:
                print(f"⚠️ [错误] 无法解析技能文件 '{filename}': {e}")
                
    return skill_lib

# 🌟 启动时执行一次聚合，生成全局的技能字典 (长驻内存，极速路由)
SKILL_LIBRARY = _build_skill_library()

def route_dynamic_skills(chunk_content: str) -> str:
    """
    自动组装包含全局特权声明的动态技能 Layer 3。
    对外暴露给 critic.py 共用考纲。
    """
    mounted_exp_rules = []
    mounted_imp_rules = []
    content_lower = chunk_content.lower()
    
    for skill_name, skill_info in SKILL_LIBRARY.items():
        # 只要命中该技能的任意一个关键字
        for kw in skill_info["keywords"]:
            if kw.lower() in content_lower:
                print(f"    🔌 [技能挂载]: 侦测到关键字 '{kw}'，注入 <{skill_name}> 考纲！")
                
                if skill_info.get("explicit_rules"):
                    mounted_exp_rules.append(f"【{skill_name} 显式审查】\n{skill_info['explicit_rules']}")
                if skill_info.get("implicit_rules"):
                    mounted_imp_rules.append(f"【{skill_name} 隐式衍生】\n{skill_info['implicit_rules']}")
                break # 命中一个关键字即可挂载该技能，跳出内层循环

    # 如果没有挂载任何技能，返回默认提示
    if not mounted_exp_rules and not mounted_imp_rules:
        return "【专属验证经验】当前文本无特定协议特征，请遵循通用验证基石法则。"
        
    # 🌟 核心组装：将“隐式推导特权”固化为系统级统一声明！
    final_layer3 = "【🔥 动态挂载专家技能库 (Dynamic Skill Library)】\n"
    
    if mounted_exp_rules:
        final_layer3 += "以下是基于显式原文的专属规则：\n" + "\n".join(mounted_exp_rules) + "\n\n"
        
    if mounted_imp_rules:
        final_layer3 += """
🌟🌟🌟 【系统级最高授权：统一隐式推导特权】 🌟🌟🌟
针对当前模块，你被授予了“专家级隐式推导”特权。
即使原文没有明确描述以下行为，你也【必须】强制衍生以下列出的测试点！
【反标豁免权】：对于这些隐式推导点，你可以直接摘录原文中提及相关接口/信号（如 ready/sram_en 等触发关键字）的那句话作为 `spec_quote`，绝不判定为幻觉！
--------------------------------------------------
"""
        final_layer3 += "\n".join(mounted_imp_rules) + "\n"
        
    return final_layer3

# =====================================================================
# [Step 4] Maker: 扁平化循环提取器
# =====================================================================
def extract_testpoints_from_chunk(client, model_name: str, chunk: dict, global_context: dict, critic_feedback: str = "") -> RawTestpointList:
    schema_json = RawTestpointList.model_json_schema()
    
    # [🧊 Layer 1 & 2] 从外部文件夹动态拉取宏观纪律
    LAYER_1_META = _load_prompt_file('layer1_meta.md')
    LAYER_2_BASE = _load_prompt_file('layer2_base.md')
    
    # [🧩 Layer 3: 业务技能层] 动态路由与特权装配
    LAYER_3_SKILLS = route_dynamic_skills(chunk['content'])
    
    # [📐 Layer 4: 结构约束层] 强绑定代码逻辑，留在 Python 中最安全
    LAYER_4_SCHEMA = f"""
    【强制输出格式】
    必须符合以下 JSON Schema，绝不妥协：
    {json.dumps(schema_json, ensure_ascii=False, indent=2)}
    
    【元数据字段 (Metadata) 提取规范】：
    1. priority (优先级): 
       - P0: 核心数据通路、复位默认状态、模块基础使能。
       - P1: 常规边界值测试、配置寄存器读写、常规协议握手。
       - P2: 极端 Corner (如长反压、同拍并发冲突)、极低概率的越界报错。
    2. 二义性预警雷达 (is_spec_ambiguous): 
       - 如果你发现 Spec 原文中存在：条件未定义全、时序含糊或自相矛盾。强制设为 True，并在 ambiguity_note 中写明“前端设计需要澄清：...”。
       - 正常清晰的描述设为 False，note 留空。
    
    【🔗 spec_quote 提取与拼接铁律】：
    1. 原话提取：必须是一字不差复制原文！（注：被授予特权的隐式推导规则除外）。
    2. 🌟 强制拼接章节号前缀：你【必须】从当前 Chunk 的标题（或上方最近的 Markdown 标题）中提取出章节号，并拼接在原话的最前面！
       - 错误示范："模块在复位期间所有AXI VALID信号拉低。"
       - 正确示范："[1.1 AXI总线复位] 模块在复位期间所有AXI VALID信号拉低。"
    """
    
    # 🌟 终极组装：系统级 Prompt
    system_prompt = f"{LAYER_1_META}\n\n{LAYER_2_BASE}\n\n{LAYER_3_SKILLS}\n\n{LAYER_4_SCHEMA}"
    
    # 🌟 动态注入 Critic 的打回意见（Maker-Checker 闭环核心）
    feedback_section = f"\n\n【⚠️ 架构师打回反馈 (自我修正指令)】\n以下是你上一次遗漏的关键硬件行为证据，本次提取必须针对它们补全测试点：\n{critic_feedback}" if critic_feedback else ""
    
    user_prompt = f"""
    【全局上下文 (Global Context)】
    {json.dumps(global_context, ensure_ascii=False)}
    
    【待处理的业务文档块 (Chunk: {chunk['group_name']})】
    {chunk['content']}{feedback_section}
    """
    
    print(f"  🔍 正在显微镜扫描 Chunk [{chunk['group_name']}] ...")
    
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        response_format={"type": "json_object"}, 
        temperature=0.1,
        max_tokens=8192  # 🌟 新增这一行！DeepSeek 最大支持 8192 词的超长输出！
    )
    
    try:
        return RawTestpointList.model_validate_json(response.choices[0].message.content)
    except Exception as e:
        print(f"  ❌ 提取格式校验失败: {e}")
        return RawTestpointList(testpoints=[])