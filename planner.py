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
from schemas import SemanticChunkingPlan
from extractor import extract_testpoints_from_chunk
from cluster import generate_tag_mapping, build_testpoint_tree
from critic import audit_extracted_testpoints
from codex_client import CodexChatClient

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
    parser.add_argument("-i", "--input", help="待解析的 Spec Markdown 文档路径")
    parser.add_argument("-o", "--output", help="输出 CSV 路径；不指定时自动生成")
    parser.add_argument("--backend", choices=["openai", "codex"], help="大模型后端；默认 openai，使用原版 API 配置")
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
def generate_chunking_plan(intro_text: str, toc_string: str) -> SemanticChunkingPlan:
    schema_json = SemanticChunkingPlan.model_json_schema()
    
    system_prompt = f"""
    你是一个资深的数字IC验证架构师 (DV Architect)。
    你的任务是阅读一份硬件模块规范 (Spec) 的【前言摘要】和【大纲目录】，并为其制定验证规划图纸。
    
    你需要完成两件事：
    1. Global Context 提取：从前言中提取全局时钟、复位(及有效电平)、基地址、总线协议等。找不到填 'N/A'。
    2. Chunk Merging 规划：根据目录结构，将高内聚、篇幅短的子章节组合成一个 MergeGroup。
       - 例如，如果 3.1 和 3.2 都是讲中断寄存器，请将它们合并。
       - 确保全篇目录都被合理分配，不要遗漏。
       
    ！！！严格指令！！！
    你必须且只能输出严格的 JSON 格式。你的 JSON 结构必须完全符合以下 JSON Schema 定义，绝不能添加任何其他的说明文字：
    {json.dumps(schema_json, ensure_ascii=False, indent=2)}
    """
    
    print(f"🧠 正在呼叫大模型 [{LLM_MODEL_NAME}] 进行全局探路与规划...")
    
    response = client.chat.completions.create(
        model=LLM_MODEL_NAME,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"【前言摘要】\n{intro_text}\n\n【大纲目录 TOC】\n{toc_string}"}
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )
    
    plan_obj = SemanticChunkingPlan.model_validate_json(response.choices[0].message.content)
    return plan_obj

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
    client = build_llm_client()
    
    # --- 交互式获取参数 ---
    raw_input = args.input or input("📂 请输入待解析的 Spec 文档路径 (支持拖拽文件到窗口): ").strip()
    input_path = raw_input.strip("'").strip('"') # 强力清洗终端自带的引号
    
    if not os.path.exists(input_path):
        print(f"\n❌ 致命错误: 找不到文件 '{input_path}'，请检查路径是否正确！")
        sys.exit(1)
        
    if args.audit is None:
        audit_choice = input("🕵️ 是否开启 Critic 审计闭环 (耗时较长，但防漏测)? [Y/n 默认开启]: ").strip().lower()
        ENABLE_CRITIC_AUDIT = (audit_choice != 'n')
    else:
        ENABLE_CRITIC_AUDIT = args.audit
    
    # 🌟 自动生成完美的文件名: DV_Testplan_源文件名_月日_时分.csv
    base_name = os.path.splitext(os.path.basename(input_path))[0]
    timestamp = datetime.datetime.now().strftime("%m%d_%H%M")
    output_file = args.output or f"DV_Testplan_{base_name}_{timestamp}.csv"
    
    print(f"\n⚙️ 配置完成！")
    print(f"   - 输入文档: {input_path}")
    print(f"   - 审计模式: {'开启 🛡️' if ENABLE_CRITIC_AUDIT else '关闭 ⚡'}")
    print(f"   - 产物路径: {output_file}\n")
    print("⏳ 正在唤醒 AI 引擎，请稍候...\n")
    
    # --- 开始业务流程 ---
    print(f"📄 正在加载文档: {input_path}")
    with open(input_path, "r", encoding="utf-8") as f:
        markdown_text = f.read()
    
    intro, toc = extract_toc_and_intro(markdown_text)
    
    try:
        plan = generate_chunking_plan(intro, toc)
        print("\n✅ 验证规划图纸生成成功！")
        print(f"🌐 [提取的全局上下文]:\n{plan.global_context}\n")
        
        print("\n🔪 正在启动 Python 物理切块执行器...")
        chunks = execute_physical_chunking(markdown_text, plan)
        print(f"✅ 成功切分出 {len(chunks)} 个独立的高内聚文本块！\n")

        # ==========================================
        # 🚀 启动 [Step 4 & 6] Maker-Checker 闭环流水线
        # ==========================================
        print(f"🏭 启动 AI 提取流水线...")
        all_flat_testpoints = []
        
        for i, chunk in enumerate(chunks):
            print(f"\n[{i+1}/{len(chunks)}] 处理 Chunk: {chunk['group_name']}")
            critic_feedback = "" 
            current_chunk_points = []
            
            for retry in range(MAX_RETRY):
                extracted_obj = extract_testpoints_from_chunk(client, LLM_MODEL_NAME, chunk, plan.global_context, critic_feedback)
                current_chunk_points = extracted_obj.testpoints
                
                if not ENABLE_CRITIC_AUDIT:
                    print(f"  ⚡ [极速模式]: 提取了 {len(current_chunk_points)} 个测试点。")
                    break
                    
                print("  🕵️ Critic 正在进行防漏测审计...")
                audit_report = audit_extracted_testpoints(client, LLM_MODEL_NAME, chunk, current_chunk_points)
                
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

            all_flat_testpoints.extend(current_chunk_points)

        # ==========================================
        # 🚀 启动 [Step 5] 后置标签聚合与建树
        # ==========================================
        if all_flat_testpoints:
            print("\n======================================================")
            print("🌳 启动结构化建树引擎 (The Clustering LLM)...")
            
            unique_tags = list(set([tp.raw_tag for tp in all_flat_testpoints]))
            print(f"  📊 从 {len(all_flat_testpoints)} 个测试点中，提炼出 {len(unique_tags)} 个不重复特征标签。")
            
            mapping_obj = generate_tag_mapping(client, LLM_MODEL_NAME, unique_tags)
            final_tree = build_testpoint_tree(all_flat_testpoints, mapping_obj.mapping_dict)
            
            # ==========================================
            # 🏆 呈现与导出
            # ==========================================
            print("\n🎉 [最终交付物：验证测试点树状矩阵]")
            print("======================================================")
            
            for primary_idx, primary_cat in enumerate(sorted(final_tree.keys())):
                # 🌟 正则魔法：从 "6.corner类" 中提取出 "6"，找不到就用索引
                p_match = re.search(r'\d+', primary_cat)
                p_num = p_match.group() if p_match else str(primary_idx + 1)
                
                print(f"\n📂 【{primary_cat}】")
                for secondary_idx, secondary_cat in enumerate(sorted(final_tree[primary_cat].keys())):
                    # 🌟 正则魔法：从 "6.1 AXI边界" 中提取出小数点后的 "1"
                    s_match = re.search(r'\d+\.(\d+)', secondary_cat)
                    s_num = s_match.group(1) if s_match else str(secondary_idx + 1)
                    
                    print(f"  └─ 📁 {secondary_cat}")
                    leaf_nodes = final_tree[primary_cat][secondary_cat]
                    for tp_idx, tp in enumerate(leaf_nodes, 1):
                        # 组装完美对齐的编号！
                        tp_id = f"TP_{p_num}.{s_num}.{tp_idx}"
                        print(f"      ├─ 📄 [{tp_id}] {tp.summary} (原标签: {tp.raw_tag})")
                        
            print("\n======================================================")
            print("🎯 恭喜！您已成功将一份纯文本 Spec，无损转化为企业级树状 Testplan！")
            
            def write_csv(filepath):
                with open(filepath, mode='w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        "测试点编号", "一级分类", "二级分类", "优先级", 
                        "特征标签", "测试点摘要", "详细描述", 
                        "🔗 原文溯源 (反标)", "⚠️ 存疑 (Spec Bug?)", "💬 缺陷/二义性说明"
                    ])
                    for primary_idx, primary_cat in enumerate(sorted(final_tree.keys())):
                        p_match = re.search(r'\d+', primary_cat)
                        p_num = p_match.group() if p_match else str(primary_idx + 1)
                        
                        for secondary_idx, secondary_cat in enumerate(sorted(final_tree[primary_cat].keys())):
                            s_match = re.search(r'\d+\.(\d+)', secondary_cat)
                            s_num = s_match.group(1) if s_match else str(secondary_idx + 1)
                            
                            for tp_idx, tp in enumerate(final_tree[primary_cat][secondary_cat], 1):
                                tp_id = f"TP_{p_num}.{s_num}.{tp_idx}"
                                writer.writerow([
                                    tp_id, primary_cat, secondary_cat, tp.priority, 
                                    tp.raw_tag, tp.summary, tp.details, 
                                    tp.spec_quote, "TRUE 🚨" if tp.is_spec_ambiguous else "", tp.ambiguity_note
                                ])
            
            try:
                write_csv(output_file)
                print(f"\n✅ 导出成功！请在当前目录下用 Excel 打开 【{output_file}】 检查成果！")
            except PermissionError:
                # 触发防丢机制，在后缀前加上 _备用
                fallback_file = output_file.replace(".csv", "_备用.csv")
                print(f"\n⚠️ [警告] 默认文件 '{output_file}' 被占用锁定！")
                print(f"🛡️ [数据防丢机制已启动] 正在为您保存至新文件: {fallback_file}")
                write_csv(fallback_file)
                print(f"✅ 备用导出成功！请打开 【{fallback_file}】")

    except Exception as e:
        import traceback
        print(f"\n❌ 流水线崩溃: {e}")
        print(" 详细的报错追踪信息如下：")
        traceback.print_exc()
