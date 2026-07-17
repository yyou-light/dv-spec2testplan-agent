import re
import os
import sys
import json
import csv
import datetime
import argparse
from dotenv import load_dotenv
from openai import OpenAI

from chunker import execute_physical_chunking
from schemas import (
    IndexedTestpoint,
    RawTestpointBundle,
    SemanticChunkingPlan,
)
from extractor import extract_testpoints_from_chunk, render_selected_skill_rules
from cluster import (
    apply_testpoint_splits,
    build_testpoint_tree,
    classify_testpoints,
    generate_classification_taxonomy,
    review_testpoint_atomicity,
    resolve_category_gaps,
)
from critic import audit_extracted_testpoints
from codex_client import CodexChatClient
from spec_loader import load_spec_as_markdown
from skill_router import build_chunk_skill_prompts, build_semantic_skill_routing_plan

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass
# =====================================================================
# ⚙️ [全局大模型配置区] - 绝对安全的安全脱敏机制
# =====================================================================
LLM_MODEL_NAME = "deepseek-chat"

MAX_RETRY = 2 # 如果被打回，最多重修次数

def build_llm_client():
    global LLM_MODEL_NAME

    # 加载当前目录下的 .env 文件
    load_dotenv()

    backend = os.getenv("DV_LLM_BACKEND", "openai").strip().lower()
    if backend == "codex":
        codex_model = os.getenv("DV_CODEX_MODEL") or "gpt-5.5"
        LLM_MODEL_NAME = codex_model
        return CodexChatClient(
            codex_exe=os.getenv("DV_CODEX_EXE") or None,
            cwd=os.getcwd(),
            model_name=codex_model,
            sandbox=os.getenv("DV_CODEX_SANDBOX", "read-only"),
            timeout_sec=int(os.getenv("DV_CODEX_TIMEOUT_SEC", "1800")),
            ignore_user_config=os.getenv("DV_CODEX_IGNORE_USER_CONFIG", "1") != "0",
        )

    if backend != "openai":
        print(f"❌ 致命错误: 未知 DV_LLM_BACKEND={backend}，支持 codex/openai")
        sys.exit(1)

    LLM_MODEL_NAME = os.getenv("DV_LLM_MODEL_NAME", "deepseek-chat")

    # 从环境变量中读取，绝不硬编码在代码里！
    llm_api_key = os.getenv("DV_LLM_API_KEY")
    if not llm_api_key:
        print("❌ 致命错误: 未检测到 DV_LLM_API_KEY 环境变量！")
        print("💡 解决方案: 请在当前目录下新建一个 '.env' 文件，并写入：DV_LLM_API_KEY=你的真实Key")
        sys.exit(1)

    return OpenAI(
        api_key=llm_api_key,
        base_url=os.getenv("DV_LLM_BASE_URL", "https://api.deepseek.com")
    )

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DV Spec2Testplan Agent")
    parser.add_argument("-i", "--input", help="待解析的 Spec 文档路径，支持 md/txt/docx/pdf")
    parser.add_argument("-o", "--output", help="输出 CSV 路径；不指定时自动生成")
    parser.add_argument("--backend", choices=["openai", "codex"], help="大模型后端；默认 openai，使用原版 API 配置")
    parser.add_argument("--dump-normalized-spec", help="将输入适配后的标准 Markdown 写入指定路径，便于检查章节识别结果")
    parser.add_argument("--normalize-only", action="store_true", help="只执行输入适配并退出，需配合 --dump-normalized-spec 使用")
    parser.add_argument("--dump-raw-testpoints", help="保存分类前的测试点和全局上下文 JSON；不指定时随 CSV 自动生成")
    parser.add_argument("--classify-only", action="store_true", help="将 --input 视为 raw testpoint JSON，只重新分类和导出 CSV")
    audit_group = parser.add_mutually_exclusive_group()
    audit_group.add_argument("--audit", dest="audit", action="store_const", const=True, default=None, help="开启 Critic 审计")
    audit_group.add_argument("--no-audit", dest="audit", action="store_const", const=False, help="关闭 Critic 审计")
    return parser.parse_args()

# =====================================================================
# 1. 预处理：纯 Python 提取目录 (TOC) 和前言
# =====================================================================
def extract_toc_and_intro(markdown_text: str) -> tuple[str, str]:
    lines = markdown_text.split('\n')
    intro_lines, toc_lines = [], []
    in_intro = True
    
    for line in lines:
        match = re.match(r'^(#{1,6})\s+(.*)', line)
        if match:
            in_intro = False
            level = len(match.group(1))
            indent = "  " * (level - 1)
            toc_lines.append(f"{indent}- {match.group(2)}")
        elif in_intro and line.strip():
            intro_lines.append(line)
            
    return "\n".join(intro_lines), "\n".join(toc_lines)

# =====================================================================
# 2. 调用大模型：生成全局上下文与切块方案
# =====================================================================
def generate_chunking_plan(
    llm_client,
    model_name: str,
    markdown_text: str,
    toc_string: str,
) -> SemanticChunkingPlan:
    schema_json = SemanticChunkingPlan.model_json_schema()
    
    system_prompt = f"""
    你是一个资深的数字IC验证架构师 (DV Architect)。
    你的任务是阅读一份完整硬件模块规范 (Spec)，建立跨章节全局事实表，并制定验证切块图纸。
    
    你需要完成两件事：
    1. Global Context 提取：
       - 必须阅读完整 Spec，而不是只依赖前言或目录。
       - 提取模块职责、时钟复位、接口协议与角色、位宽、地址映射、寄存器、时序、协议限制、错误响应、工作模式和并发约束。
       - 每条 confirmed_fact 必须包含章节和一字不差的原文 evidence，不得推测设计结论。
       - unresolved_questions 只记录会影响 Spec 已声明功能验证的真实缺口；不要罗列协议所有可选能力。
    2. Chunk Merging 规划：根据目录结构，将高内聚、篇幅短的子章节组合成一个 MergeGroup。
       - 例如，如果 3.1 和 3.2 都是讲中断寄存器，请将它们合并。
       - 确保全篇目录都被合理分配，不要遗漏。
       
    ！！！严格指令！！！
    你必须且只能输出严格的 JSON 格式。你的 JSON 结构必须完全符合以下 JSON Schema 定义，绝不能添加任何其他的说明文字：
    {json.dumps(schema_json, ensure_ascii=False, indent=2)}
    """
    
    print(f"🧠 正在呼叫大模型 [{model_name}] 阅读完整 Spec 并进行全局探路与规划...")
    
    response = llm_client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"【完整 Spec 正文】\n{markdown_text}\n\n"
                    f"【大纲目录 TOC】\n{toc_string}"
                ),
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    
    plan_obj = SemanticChunkingPlan.model_validate_json(response.choices[0].message.content)
    return plan_obj


def artifact_path_for(output_file: str, suffix: str) -> str:
    stem, _ = os.path.splitext(output_file)
    return f"{stem}{suffix}"


def write_json_artifact(filepath: str, payload: dict) -> None:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def category_sort_key(value: str) -> tuple:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value))
    return numbers or (999,)


def classify_and_export(
    llm_client,
    model_name: str,
    global_context: dict,
    indexed_testpoints: list[IndexedTestpoint],
    output_file: str,
    source_path: str,
    audit_enabled: bool,
) -> None:
    print("\n======================================================")
    print("🌳 启动完整语义分类与建树引擎...")

    print(f"  正在独立审查 {len(indexed_testpoints)} 条测试点的原子性...")
    atomicity_review = review_testpoint_atomicity(
        llm_client,
        model_name,
        global_context,
        indexed_testpoints,
    )
    atomicity_file = artifact_path_for(output_file, ".atomicity.json")
    write_json_artifact(
        atomicity_file,
        {
            "input_testpoint_count": len(indexed_testpoints),
            "split_count": len(atomicity_review.splits),
            "review": atomicity_review.model_dump(),
        },
    )
    print(f"  - 原子性审查文件: {atomicity_file}")

    indexed_testpoints = apply_testpoint_splits(
        indexed_testpoints,
        atomicity_review,
    )
    atomic_bundle = RawTestpointBundle(
        source_path=source_path,
        global_context=global_context,
        audit_enabled=audit_enabled,
        indexed_testpoints=indexed_testpoints,
    )
    atomic_file = artifact_path_for(output_file, ".atomic.raw.json")
    write_json_artifact(atomic_file, atomic_bundle.model_dump())
    print(
        f"  - 原子化测试点文件: {atomic_file} "
        f"({len(indexed_testpoints)} 条)"
    )

    taxonomy = generate_classification_taxonomy(
        llm_client,
        model_name,
        global_context,
        indexed_testpoints,
    )
    classification = classify_testpoints(
        llm_client,
        model_name,
        global_context,
        indexed_testpoints,
        taxonomy,
    )
    taxonomy, classification = resolve_category_gaps(
        llm_client,
        model_name,
        global_context,
        indexed_testpoints,
        taxonomy,
        classification,
    )

    classification_file = artifact_path_for(output_file, ".classification.json")
    write_json_artifact(
        classification_file,
        {
            "taxonomy": taxonomy.model_dump(),
            "classification": classification.model_dump(),
            "atomicity_review": atomicity_review.model_dump(),
        },
    )
    print(f"  - 分类审计文件: {classification_file}")

    split_candidates = [
        assignment
        for assignment in classification.assignments
        if assignment.needs_split
    ]
    if split_candidates:
        candidate_ids = [assignment.testpoint_id for assignment in split_candidates]
        raise ValueError(
            "分类器违反职责边界并再次请求拆分，停止导出: "
            f"{candidate_ids}"
        )

    final_tree = build_testpoint_tree(indexed_testpoints, taxonomy, classification)
    assignment_by_id = {
        assignment.testpoint_id: assignment
        for assignment in classification.assignments
    }

    print("\n🎉 [最终交付物：验证测试点树状矩阵]")
    print("======================================================")
    for primary_cat in sorted(final_tree, key=category_sort_key):
        print(f"\n📂 【{primary_cat}】")
        for secondary_cat in sorted(final_tree[primary_cat], key=category_sort_key):
            print(f"  └─ 📁 {secondary_cat}")
            leaf_nodes = final_tree[primary_cat][secondary_cat]
            primary_number = re.search(r"\d+", primary_cat).group()
            secondary_match = re.search(r"\d+\.(\d+)", secondary_cat)
            secondary_number = secondary_match.group(1) if secondary_match else "1"
            for tp_index, indexed in enumerate(leaf_nodes, start=1):
                point = indexed.testpoint
                tp_id = f"TP_{primary_number}.{secondary_number}.{tp_index}"
                print(
                    f"      ├─ 📄 [{tp_id}] {point.summary} "
                    f"(原标签: {point.raw_tag}, 内部ID: {indexed.testpoint_id})"
                )

    def write_csv_file(filepath: str) -> None:
        with open(filepath, mode="w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow([
                "测试点编号", "一级分类", "二级分类", "优先级",
                "特征标签", "测试点摘要", "详细描述",
                "🔗 依据反标", "⚠️ 存疑 (Spec Bug?)", "💬 缺陷/二义性说明",
                "内部测试点ID", "分类置信度", "分类依据", "混合意图说明",
                "合法性判定", "主验证意图", "Corner触发条件", "Corner判定依据",
                "结果关注域", "错误机制",
                "二级目录匹配依据",
            ])
            for primary_cat in sorted(final_tree, key=category_sort_key):
                primary_number = re.search(r"\d+", primary_cat).group()
                for secondary_cat in sorted(final_tree[primary_cat], key=category_sort_key):
                    secondary_match = re.search(r"\d+\.(\d+)", secondary_cat)
                    secondary_number = secondary_match.group(1) if secondary_match else "1"
                    for tp_index, indexed in enumerate(
                        final_tree[primary_cat][secondary_cat],
                        start=1,
                    ):
                        point = indexed.testpoint
                        assignment = assignment_by_id[indexed.testpoint_id]
                        tp_id = f"TP_{primary_number}.{secondary_number}.{tp_index}"
                        writer.writerow([
                            tp_id,
                            primary_cat,
                            secondary_cat,
                            point.priority,
                            point.raw_tag,
                            point.summary,
                            point.details,
                            point.spec_quote,
                            "TRUE 🚨" if point.is_spec_ambiguous else "",
                            point.ambiguity_note,
                            indexed.testpoint_id,
                            assignment.confidence,
                            assignment.reasoning,
                            assignment.split_reason if assignment.needs_split else "",
                            assignment.legality,
                            assignment.verification_intent,
                            ",".join(assignment.corner_triggers),
                            assignment.corner_evidence,
                            assignment.outcome_focus,
                            "; ".join(assignment.error_mechanisms),
                            assignment.category_fit_reason,
                        ])

    try:
        write_csv_file(output_file)
        print(f"\n✅ 导出成功: {output_file}")
    except PermissionError:
        stem, extension = os.path.splitext(output_file)
        fallback_file = f"{stem}_备用{extension or '.csv'}"
        print(f"\n⚠️ 输出文件被占用，改存为: {fallback_file}")
        write_csv_file(fallback_file)
        print(f"✅ 备用导出成功: {fallback_file}")

# =====================================================================
# 3. 🚀 主执行入口 (交互式向导)
# =====================================================================
if __name__ == "__main__":
    args = parse_args()
    if args.backend:
        os.environ["DV_LLM_BACKEND"] = args.backend

    print("\n======================================================")
    print("🚀 欢迎使用 DV AI Agent (智能验证计划提取引擎) v0.1")
    print("======================================================")
    
    # --- 交互式获取参数 ---
    raw_input = args.input or input("📂 请输入待解析的 Spec 文档路径 (支持拖拽文件到窗口): ").strip()
    input_path = raw_input.strip("'").strip('"') # 强力清洗终端自带的引号
    
    if not os.path.exists(input_path):
        print(f"\n❌ 致命错误: 找不到文件 '{input_path}'，请检查路径是否正确！")
        sys.exit(1)

    if args.classify_only and args.normalize_only:
        print("❌ --classify-only 与 --normalize-only 不能同时使用。")
        sys.exit(1)

    base_name = os.path.splitext(os.path.basename(input_path))[0]
    timestamp = datetime.datetime.now().strftime("%m%d_%H%M")
    output_file = args.output or f"DV_Testplan_{base_name}_{timestamp}.csv"

    if args.classify_only:
        print("\n⚙️ 配置完成！")
        print(f"   - Raw Testpoint: {input_path}")
        print("   - 输出模式: 仅重新分类，不运行 Maker/Critic")
        print(f"   - 产物路径: {output_file}\n")
        try:
            with open(input_path, "r", encoding="utf-8") as f:
                bundle = RawTestpointBundle.model_validate_json(f.read())
            client = build_llm_client()
            classify_and_export(
                client,
                LLM_MODEL_NAME,
                bundle.global_context,
                bundle.indexed_testpoints,
                output_file,
                bundle.source_path,
                bundle.audit_enabled,
            )
            sys.exit(0)
        except Exception as e:
            import traceback
            print(f"\n❌ 分类复跑失败: {e}")
            traceback.print_exc()
            sys.exit(1)
        
    if args.normalize_only:
        ENABLE_CRITIC_AUDIT = False
    elif args.audit is None:
        audit_choice = input("🕵️ 是否开启 Critic 审计闭环 (耗时较长，但防漏测)? [Y/n 默认开启]: ").strip().lower()
        ENABLE_CRITIC_AUDIT = (audit_choice != 'n')
    else:
        ENABLE_CRITIC_AUDIT = args.audit
    
    print(f"\n⚙️ 配置完成！")
    print(f"   - 输入文档: {input_path}")
    if args.normalize_only:
        print("   - 输出模式: 仅标准化输入，不生成 CSV")
    else:
        print(f"   - 审计模式: {'开启 🛡️' if ENABLE_CRITIC_AUDIT else '关闭 ⚡'}")
        print(f"   - 产物路径: {output_file}")
    print()
    print("⏳ 正在准备处理流程，请稍候...\n")
    
    # --- 开始业务流程 ---
    print(f"📄 正在加载文档: {input_path}")
    loaded_spec = load_spec_as_markdown(input_path)
    markdown_text = loaded_spec.markdown_text
    print(
        "   - 输入格式: "
        f"{loaded_spec.report.source_format}, "
        f"识别标题: {loaded_spec.report.heading_count}, "
        f"推断标题: {loaded_spec.report.inferred_heading_count}, "
        f"结构置信度: {loaded_spec.report.confidence}"
    )
    for warning in loaded_spec.report.warnings:
        print(f"   - 结构提示: {warning}")
    if args.dump_normalized_spec:
        with open(args.dump_normalized_spec, "w", encoding="utf-8") as f:
            f.write(markdown_text)
        print(f"   - 标准化 Markdown 已写入: {args.dump_normalized_spec}")
    if args.normalize_only:
        if not args.dump_normalized_spec:
            print("❌ --normalize-only 需要配合 --dump-normalized-spec 指定输出路径。")
            sys.exit(1)
        print("✅ 仅执行输入适配，未调用大模型。")
        sys.exit(0)

    client = build_llm_client()
    
    _, toc = extract_toc_and_intro(markdown_text)
    
    try:
        plan = generate_chunking_plan(client, LLM_MODEL_NAME, markdown_text, toc)
        print("\n✅ 验证规划图纸生成成功！")
        global_context = plan.global_context.model_dump()
        print(
            "🌐 [完整 Spec 全局上下文]:\n"
            f"{json.dumps(global_context, ensure_ascii=False, indent=2)}\n"
        )
        
        print("\n🔪 正在启动 Python 物理切块执行器...")
        chunks = execute_physical_chunking(markdown_text, plan)
        print(f"✅ 成功切分出 {len(chunks)} 个独立的高内聚文本块！\n")

        skill_router_mode = os.getenv("DV_SKILL_ROUTER", "semantic").strip().lower()
        skill_prompts_by_chunk = {}
        if skill_router_mode == "semantic":
            skill_routing_plan = build_semantic_skill_routing_plan(
                client,
                LLM_MODEL_NAME,
                markdown_text,
                chunks,
                global_context,
            )
            skill_prompts_by_chunk = build_chunk_skill_prompts(skill_routing_plan)
            print(
                f"✅ 全局 Skill 路由完成: "
                f"{len(skill_routing_plan.applications)} 条规则已分配。\n"
            )
            for application in skill_routing_plan.applications:
                targets = ", ".join(application.target_chunks)
                print(f"   - {application.rule_ref} -> {targets}")
            print()
        elif skill_router_mode == "keyword":
            print("⚠️ 使用兼容关键词路由模式；已启用安全词边界匹配。\n")
        else:
            raise ValueError(
                f"未知 DV_SKILL_ROUTER={skill_router_mode}，支持 semantic/keyword"
            )

        # ==========================================
        # 🚀 启动 [Step 4 & 6] Maker-Checker 闭环流水线
        # ==========================================
        print(f"🏭 启动 AI 提取流水线...")
        all_indexed_testpoints = []
        
        for i, chunk in enumerate(chunks):
            print(f"\n[{i+1}/{len(chunks)}] 处理 Chunk: {chunk['group_name']}")
            critic_feedback = "" 
            current_chunk_points = []
            chunk_skill_prompt = None
            if skill_router_mode == "semantic":
                chunk_skill_prompt = skill_prompts_by_chunk.get(
                    chunk["group_name"],
                    render_selected_skill_rules([]),
                )
            
            for retry in range(MAX_RETRY):
                extracted_obj = extract_testpoints_from_chunk(
                    client,
                    LLM_MODEL_NAME,
                    chunk,
                    global_context,
                    critic_feedback,
                    chunk_skill_prompt,
                )
                current_chunk_points = extracted_obj.testpoints
                
                if not ENABLE_CRITIC_AUDIT:
                    print(f"  ⚡ [极速模式]: 提取了 {len(current_chunk_points)} 个测试点。")
                    break
                    
                print("  🕵️ Critic 正在进行防漏测审计...")
                audit_report = audit_extracted_testpoints(
                    client,
                    LLM_MODEL_NAME,
                    chunk,
                    current_chunk_points,
                    chunk_skill_prompt,
                )
                
                if audit_report.is_passed:
                    print(f"  ✅ [审计通过]: 未发现漏测 ({audit_report.critic_notes})")
                    break 
                else:
                    print(f"  ⚠️ [审计打回 - 第 {retry+1} 次]: 发现 {len(audit_report.omissions)} 处潜在漏测！")
                    for om in audit_report.omissions:
                        print(f"      - 漏测抓包: {om.missed_sentence}")
                    
                    if retry == MAX_RETRY - 1:
                        print(f"  ⚠️ [探讨结束]: Maker 与 Critic 已探讨 {MAX_RETRY} 轮。保留当前最优提取版本，继续推进流水线...")
                        break
                        
                    critic_feedback = "\n".join([f"- 遗漏原文: '{o.missed_sentence}' (原因: {o.reasoning})" for o in audit_report.omissions])
                    print("  🔄 正在启动自我修正引擎重新提取...")

            for point in current_chunk_points:
                all_indexed_testpoints.append(
                    IndexedTestpoint(
                        testpoint_id=f"RTP_{len(all_indexed_testpoints) + 1:04d}",
                        source_chunk=chunk["group_name"],
                        testpoint=point,
                    )
                )

        if not all_indexed_testpoints:
            raise RuntimeError("Maker 未生成任何测试点，停止分类和导出。")

        raw_bundle = RawTestpointBundle(
            source_path=input_path,
            global_context=global_context,
            audit_enabled=ENABLE_CRITIC_AUDIT,
            indexed_testpoints=all_indexed_testpoints,
        )
        raw_bundle_file = (
            args.dump_raw_testpoints
            or artifact_path_for(output_file, ".raw.json")
        )
        write_json_artifact(raw_bundle_file, raw_bundle.model_dump())
        print(f"\n💾 分类前测试点已保存: {raw_bundle_file}")

        classify_and_export(
            client,
            LLM_MODEL_NAME,
            global_context,
            all_indexed_testpoints,
            output_file,
            input_path,
            ENABLE_CRITIC_AUDIT,
        )

    except Exception as e:
        import traceback
        print(f"\n❌ 流水线崩溃: {e}")
        print(" 详细的报错追踪信息如下：")
        traceback.print_exc()
        sys.exit(1)
