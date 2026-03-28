import os
import json
import re
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def run_tbox_discovery(input_file="output/aggregated_ind_summaries.md", output_file="ontology/ind_schema.json"):
    """
    使用用户提供的提示词，结合全量摘要，生成 TBox Schema。
    """
    # 1. 读取 API 配置
    api_key = os.getenv("OPENVIKING_LLM_API_KEY") or os.getenv("API_KEY")
    base_url = os.getenv("OPENVIKING_LLM_API_BASE") or os.getenv("BASE_URL")
    model = os.getenv("OPENVIKING_LLM_MODEL") or os.getenv("MODEL_NAME")
    
    if not api_key:
        print("Error: API_KEY not found in .env")
        return

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 2. 读取全量摘要
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return
        
    with open(input_file, "r", encoding="utf-8") as f:
        aggregated_text = f.read()

    # 3. 构造提示词 (基于 提示词.md 中的 阶段 1)
    system_prompt = """
你是一位深耕生物医药领域 20 年的“药政合规官”与“本体论建模专家”。你擅长从繁杂的 CTD 申报资料中抽象出严密的逻辑结构。
""".strip()

    user_prompt = f"""
### Task
请深入分析以下 88 份 IND 申报资料的全量摘要，构建一个**极精细化**的 TBox 本体模型。
现有的 12 个基础大类过于抽象，请你基于摘要内容，挖掘出二级、三级子类及配套类。

我们需要提取以下维度的精细化模型：
1. **实体类 (Classes)**：
   - 临床层面：不能只有 ClinicalTrial，应包含 `Cohort` (队列), `DoseLevel` (剂量层级), `Endpoint` (研究终点), `InclusionCriteria` (入选标准) 等。
   - 药学层面：应包含 `Formulation` (剂型), `AnalyticalMethod` (分析方法), `Impurity` (杂质), `StorageCondition` (存贮条件) 等。
   - 逻辑层面：`RegulatoryBody`, `LiteratureReference`, `Guideline` 等。
2. **详细属性 (Object Properties)**：定义这些精细类之间的精密谓语（如：[剂量层级]-属于-[研究队列], [分析方法]-验证了-[药品规格]）。
3. **专家级推理公理 (Axioms)**：挖掘更隐晦的逻辑，如：“若杂质 A 超过限度 B，则必须有关联的毒理学安全性评价”。

### Constraints
- 请务必涵盖 1.3.4 (方案), 1.8 (风险管理), 模块 3 (药学), 模块 4 (非临床) 之间的交叉链条。
- 采用 JSON 格式输出 Schema 结构。
- 目标类别数量控制在 30-50 个之间，以保证图谱的表达力。

### Input Data
{aggregated_text}
""".strip()

    print(f"正在调用模型 {model} 进行 TBox 发现...")
    
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"} if "gpt-4o" in model.lower() or "grok" in model.lower() else None,
            temperature=0.3
        )
        
        content = response.choices[0].message.content
        
        # 调试用：保存原始回复
        os.makedirs("ontology", exist_ok=True)
        with open("ontology/raw_discovery_response.txt", "w", encoding="utf-8") as f_debug:
            f_debug.write(content)
            
        # 尝试清理 Markdown 代码块包裹
        if "```" in content:
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
            if match:
                content = match.group(1).strip()
            
        # 解析与修复 JSON
        try:
            schema_data = json.loads(content)
        except json.JSONDecodeError as je:
            print(f"标准 JSON 解析失败，尝试修复常见错误... {je}")
            # 简单的尾部逗号修复
            content_fixed = re.sub(r',\s*([\]}])', r'\1', content)
            schema_data = json.loads(content_fixed)
        
        # 写入结果
        with open(output_file, "w", encoding="utf-8") as out:
            json.dump(schema_data, out, ensure_ascii=False, indent=2)
            
        print(f"TBox Schema 生成成功！保存至: {output_file}")
        return schema_data
        
    except Exception as e:
        print(f"过程失败: {e}")
        return None

if __name__ == "__main__":
    run_tbox_discovery()
