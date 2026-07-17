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
                        "filename": filename,
                        "keywords": keywords,
                        "explicit_rules": parse_skill_rules(
                            exp_match.group(1).strip() if exp_match else "",
                            skill_name,
                            filename,
                            "explicit",
                        ),
                        "implicit_rules": parse_skill_rules(
                            imp_match.group(1).strip() if imp_match else "",
                            skill_name,
                            filename,
                            "implicit",
                        ),
                    }
                else:
                    print(f"⚠️ [警告] 技能文件 '{filename}' 缺少 '# keywords' 标题，已跳过。")
                    
            except Exception as e:
                print(f"⚠️ [错误] 无法解析技能文件 '{filename}': {e}")
                
    return skill_lib


def parse_skill_rules(section_text: str, skill_name: str, filename: str, kind: str) -> list[dict]:
    """
    Parse numbered skill rules and keep a stable reference for CSV review.
    Numbered rules are preferred, but old unnumbered skills remain compatible.
    """
    rules = []
    auto_index = 1
    kind_token = "EXP" if kind == "explicit" else "IMP"

    for raw_line in section_text.splitlines():
        line = raw_line.strip()
        if not line or line in {"（无）", "(无)", "无"} or "这里留空" in line:
            continue

        numbered = re.match(
            r"^[-*]?\s*(?P<rule_id>[A-Z][A-Z0-9]*-(?:EXP|IMP)-\d{3})\s*[:：]\s*(?P<text>.+)$",
            line,
        )
        if numbered:
            rule_id = numbered.group("rule_id").strip()
            rule_text = numbered.group("text").strip()
        else:
            rule_id = f"{skill_name}-{kind_token}-AUTO-{auto_index:03d}"
            auto_index += 1
            rule_text = re.sub(r"^[-*]?\s*\d+[.)、]\s*", "", line).strip()

        if not rule_text:
            continue

        rules.append(
            {
                "id": rule_id,
                "text": rule_text,
                "source_ref": f"[SKILL: {filename}#{rule_id}] {rule_text}",
                "skill_name": skill_name,
                "filename": filename,
                "kind": kind,
            }
        )

    return rules


def format_skill_rules(skill_name: str, title: str, rules: list[dict]) -> str:
    lines = [f"【{skill_name} {title}】"]
    for rule in rules:
        lines.append(f"- {rule['source_ref']}")
    return "\n".join(lines)


# 🌟 启动时执行一次聚合，生成全局的技能字典 (长驻内存，极速路由)
SKILL_LIBRARY = _build_skill_library()


def keyword_matches(text: str, keyword: str) -> bool:
    """Match protocol keywords without treating arbitrary word substrings as signals."""
    keyword = keyword.strip()
    if not keyword:
        return False

    lowered = text.casefold()
    normalized_keyword = keyword.casefold()

    if re.search(r"[\u3400-\u9fff]", normalized_keyword):
        return normalized_keyword in lowered

    token_pattern = rf"(?<![a-z0-9_]){re.escape(normalized_keyword)}(?![a-z0-9_])"
    if re.search(token_pattern, lowered):
        return True

    # Markdown code identifiers such as `ram_en` and `sram_addr` are strong signals.
    code_identifiers = re.findall(r"`([^`]+)`", lowered)
    if any(normalized_keyword in identifier.split("_") for identifier in code_identifiers):
        return True

    if normalized_keyword == "axi" and re.search(r"(?<![a-z0-9_])axi(?:3|4)(?:-lite|lite)?(?![a-z0-9_])", lowered):
        return True

    if normalized_keyword in {"ready", "valid"}:
        backticked_signal = rf"`[a-z0-9_]*{normalized_keyword}[a-z0-9_]*`"
        uppercase_signal = rf"(?<![A-Z0-9_])[A-Z][A-Z0-9_]*{normalized_keyword.upper()}(?![A-Z0-9_])"
        snake_signal = rf"(?<![a-z0-9_])[a-z0-9]+_{normalized_keyword}(?![a-z0-9_])"
        return bool(
            re.search(backticked_signal, lowered)
            or re.search(uppercase_signal, text)
            or re.search(snake_signal, lowered)
        )

    return False


def detect_skill_names(document_text: str) -> list[str]:
    """Return document-level skill candidates in stable filename order."""
    detected = []
    for skill_name in sorted(SKILL_LIBRARY):
        skill_info = SKILL_LIBRARY[skill_name]
        if any(keyword_matches(document_text, keyword) for keyword in skill_info["keywords"]):
            detected.append(skill_name)
    return detected


def get_skill_rule_catalog(skill_names: list[str] | None = None) -> dict[str, dict]:
    """Build a stable rule catalog keyed by file.md#RULE-ID."""
    selected_names = set(SKILL_LIBRARY.keys() if skill_names is None else skill_names)
    catalog = {}
    for skill_name in sorted(SKILL_LIBRARY):
        if skill_name not in selected_names:
            continue
        skill_info = SKILL_LIBRARY[skill_name]
        for rule in skill_info.get("explicit_rules", []) + skill_info.get("implicit_rules", []):
            rule_ref = f"{rule['filename']}#{rule['id']}"
            if rule_ref in catalog:
                raise ValueError(f"重复的 Skill 规则编号: {rule_ref}")
            catalog[rule_ref] = rule
    return catalog


def render_selected_skill_rules(selected_rules: list[dict]) -> str:
    """Render only the rules assigned to the current chunk."""
    if not selected_rules:
        return "【专属验证经验】当前文本无特定协议规则分配，请遵循通用验证基石法则。"

    grouped: dict[tuple[str, str], list[dict]] = {}
    for rule in selected_rules:
        key = (rule["skill_name"], rule["kind"])
        grouped.setdefault(key, []).append(rule)

    sections = ["【动态挂载专家技能库 (Global Skill Routing)】"]
    for (skill_name, kind), rules in grouped.items():
        title = "显式审查" if kind == "explicit" else "专家经验覆盖"
        sections.append(format_skill_rules(skill_name, title, rules))

    sections.append(
        """
【DV 经验覆盖纪律】
以上规则由完整 Spec 和全体 Chunk 的全局路由结果分配到当前 Chunk。
1. 这些规则是合法的 DV 经验覆盖项，不要求 Spec 逐字写出。
2. 如果完整 Spec 中存在能直接支撑测试点的原文，优先使用 Spec 原文作为依据反标。
3. 如果 Spec 中没有合适的直接支撑句，必须使用对应的 `[SKILL: file.md#RULE-ID]` 规则反标。
4. 不要为了凑 Spec 反标而引用弱相关句子，也不要在摘要或描述中写“隐式验证”。
5. 同一规则如包含多个真正不同的验证对象，可以分别成点；不要仅通过换措辞重复同一测试意图。
6. 当前 Chunk 被分配到的每条非同义规则都必须至少落实为一个有明确验证意义的测试点。
7. 对“如果模块支持”这类条件规则，如果完整 Spec 没有说明支持范围，仍需生成用于确认该能力和边界的测试点，并把真正需要澄清的支持范围标为存疑。
8. 两条规则如果验证意图实质相同，可以由同一个测试点覆盖，不要为了分别出现规则编号而制造重复。
""".strip()
    )
    return "\n\n".join(sections)

def route_dynamic_skills(chunk_content: str) -> str:
    """
    自动组装包含全局特权声明的动态技能 Layer 3。
    对外暴露给 critic.py 共用考纲。
    """
    selected_rules = []
    for skill_name in detect_skill_names(chunk_content):
        skill_info = SKILL_LIBRARY[skill_name]
        matched_keyword = next(
            keyword
            for keyword in skill_info["keywords"]
            if keyword_matches(chunk_content, keyword)
        )
        print(f"    [技能挂载]: 侦测到关键字 '{matched_keyword}'，注入 <{skill_name}> 考纲！")
        selected_rules.extend(skill_info.get("explicit_rules", []))
        selected_rules.extend(skill_info.get("implicit_rules", []))

    return render_selected_skill_rules(selected_rules)

# =====================================================================
# [Step 4] Maker: 扁平化循环提取器
# =====================================================================
def extract_testpoints_from_chunk(
    client,
    model_name: str,
    chunk: dict,
    global_context: dict,
    critic_feedback: str = "",
    skill_prompt: str | None = None,
) -> RawTestpointList:
    schema_json = RawTestpointList.model_json_schema()
    
    # [🧊 Layer 1 & 2] 从外部文件夹动态拉取宏观纪律
    LAYER_1_META = _load_prompt_file('layer1_meta.md')
    LAYER_2_BASE = _load_prompt_file('layer2_base.md')
    
    # [🧩 Layer 3: 业务技能层] 动态路由与特权装配
    LAYER_3_SKILLS = skill_prompt if skill_prompt is not None else route_dynamic_skills(chunk['content'])
    
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
       - 判断前必须先检查【全局上下文】中的完整 Spec 事实。其他章节已经定义的内容不是二义性，禁止写“当前 Chunk 未说明”。
       - Skill 经验涉及的协议可选能力如果未在 Spec 中声明支持，不应自动判为 Spec Bug；只有它会影响 Spec 已声明功能且确实无法确定预期行为时才标记。
       - 正常清晰的描述设为 False，note 留空。
    
    【🔗 spec_quote / 依据反标纪律】：
    1. Spec 直接支撑优先：如果当前 Chunk 中有能解释“为什么要测这个”的原文句子，必须一字不差复制原文。
    2. 强制拼接章节号前缀：使用 Spec 原文时，你【必须】从当前 Chunk 的标题（或上方最近的 Markdown 标题）中提取出章节号，并拼接在原话的最前面！
       - 错误示范："模块在复位期间所有AXI VALID信号拉低。"
       - 正确示范："[1.1 AXI总线复位] 模块在复位期间所有AXI VALID信号拉低。"
    3. Skill 兜底反标：如果测试点来自专家 skill，而当前 Chunk 没有合适的直接支撑句，必须填写对应 skill 规则，例如：
       "[SKILL: axi.md#AXI-IMP-004] 通道反压：确保各通道在正常工作情况下，都触发过反压(ready拉低)。"
    4. 禁止弱相关 Spec 反标：不要把只出现了 AXI、ready、sram_en 等关键词但不能支撑该测试点的句子当作 Spec 反标。
    5. 摘要写验证目的即可，不要在 summary 或 details 中写“隐式验证”。
    """
    
    # 🌟 终极组装：系统级 Prompt
    system_prompt = f"{LAYER_1_META}\n\n{LAYER_2_BASE}\n\n{LAYER_3_SKILLS}\n\n{LAYER_4_SCHEMA}"
    
    # 🌟 动态注入 Critic 的打回意见（Maker-Checker 闭环核心）
    feedback_section = f"\n\n【⚠️ 架构师打回反馈 (自我修正指令)】\n以下是你上一次遗漏的关键硬件行为证据，本次提取必须针对它们补全测试点：\n{critic_feedback}" if critic_feedback else ""
    
    user_prompt = f"""
    【全局上下文 (Global Context)】
    {json.dumps(global_context, ensure_ascii=False)}

    该上下文来自完整 Spec 的跨章节事实提取。当前 Chunk 与全局事实冲突时应标记问题；
    当前 Chunk 没有重复描述、但全局事实已经定义的内容，必须视为已定义。
    
    【待处理的业务文档块 (Chunk: {chunk['group_name']})】
    {chunk['content']}{feedback_section}
    """
    
    print(f"  正在扫描 Chunk [{chunk['group_name']}] ...")
    
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
        print(f"  提取格式校验失败: {e}")
        return RawTestpointList(testpoints=[])
