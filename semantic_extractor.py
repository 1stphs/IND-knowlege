import os
import json
import re
import glob
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from openai import OpenAI
from dotenv import load_dotenv
from typing import List, Dict

# 加载环境变量
load_dotenv()

class SemanticExtractor:
    def __init__(self, schema_path="ontology/ind_schema.json"):
        # 1. 读取 API 配置
        self.api_key = os.getenv("OPENVIKING_LLM_API_KEY") or os.getenv("API_KEY")
        self.base_url = os.getenv("OPENVIKING_LLM_API_BASE") or os.getenv("BASE_URL")
        self.model = os.getenv("OPENVIKING_LLM_MODEL") or os.getenv("MODEL_NAME")
        
        if not self.api_key:
            raise ValueError("API_KEY not found in .env")

        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        
        # 2. 加载 Schema
        with open(schema_path, "r", encoding="utf-8") as f:
            self.schema = json.load(f)
        
        # 3. 线程锁，确保写文件安全
        self.lock = threading.Lock()

    def extract_from_content(self, content: str, file_name: str, chunk_id: str = "full") -> List[Dict]:
        """
        核心抽取逻辑，支持分片调用。
        """
        system_prompt = """
你是一个极度严谨的“医药数据抽取机器人”。你的任务是像外科医生一样，从文档中剥离出结构化的事实，不准产生任何幻觉。
""".strip()

        user_prompt = f"""
### Knowledge Schema
{json.dumps(self.schema, ensure_ascii=False)}

### Task
请阅读下方的 Markdown 文档片段，按照给定的 Schema 提取所有符合条件的实体及关系。

### Requirements
1. **格式化输出**：必须以标准 JSON List 格式输出三元组 `(Subject, Predicate, Object)`。
2. **100% 溯源 (Traceability)**：每个三元组必须包含 `source_context`（原文片段）和 `source_location`（Markdown 标题路径及大致位置）。
3. **严格过滤**：任何不符合 Schema 定义的关系一律忽略，保持数据纯净。
4. **属性补全**：如果识别到数值（如发生率、时间、剂量），请将其作为实体的属性。

### Input Document Fragment (Source: {file_name}, Chunk: {chunk_id})
{content}
""".strip()

        try:
            # print(f"请求 API (Chunk: {chunk_id})...")
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1
            )
            
            resp_content = response.choices[0].message.content
            
            if "```" in resp_content:
                match = re.search(r"```(?:json)?\s*(.*?)\s*```", resp_content, re.DOTALL)
                if match:
                    resp_content = match.group(1).strip()
            
            try:
                data = json.loads(resp_content)
            except:
                # 尝试修复一些常见的 JSON 错误
                resp_content = re.sub(r',\s*]', ']', resp_content)
                resp_content = re.sub(r',\s*}', '}', resp_content)
                data = json.loads(resp_content)
            
            # 兼容各种返回格式
            triples = []
            if isinstance(data, list):
                triples = data
            elif isinstance(data, dict):
                found = False
                for key in ["triples", "data", "results", "Triples"]:
                    if key in data and isinstance(data[key], list):
                        triples = data[key]
                        found = True
                        break
                if not found:
                    triples = [data]
            
            # 验证三元组必须是字典
            valid_triples = [t for t in triples if isinstance(t, dict)]
            
            # 添加 chunk 元数据
            for t in valid_triples:
                t["chunk_id"] = chunk_id
            return valid_triples
            
        except Exception as e:
            print(f"处理文件 {file_name} 分片 {chunk_id} 失败: {e}")
            return []

    def extract_from_file(self, file_path: str) -> List[Dict]:
        """
        分片处理文件。
        """
        file_name = os.path.basename(file_path)
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 按二级标题分片
        chunks = re.split(r'\n## ', content)
        all_triples = []
        
        for i, chunk in enumerate(chunks):
            prefix = "## " if i > 0 else ""
            if len(chunk.strip()) < 50:
                continue
            
            triples = self.extract_from_content(prefix + chunk, file_name, chunk_id=f"part_{i}")
            all_triples.extend(triples)
            
        return all_triples

    def batch_process(self, input_pattern="output/mineru_markdowns/*.md", output_file="ontology/extracted_triples.json", max_workers=8):
        all_files = glob.glob(input_pattern)
        md_files = [f for f in all_files if not f.endswith(".summary.md")]
        md_files.sort()
        
        total = len(md_files)
        print(f"准备并发处理 {total} 个源文档 (线程数: {max_workers})...")
        
        # 加载已有的三元组
        existing_triples = []
        processed_files = set()
        if os.path.exists(output_file):
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    existing_triples = json.load(f)
                    for t in existing_triples:
                        if "source_md" in t:
                            processed_files.add(t["source_md"])
                print(f"检测到已处理文件: {len(processed_files)} 个。")
            except Exception:
                pass

        all_triples = existing_triples
        to_process = [f for f in md_files if os.path.basename(f) not in processed_files]
        print(f"待处理任务: {len(to_process)} 个。")

        def task(file_path):
            file_name = os.path.basename(file_path)
            try:
                print(f"  [开始] {file_name}")
                triples = self.extract_from_file(file_path)
                
                # 注入元数据
                for t in triples:
                    if isinstance(t, dict):
                        t["source_md"] = file_name
                
                # 加锁合并并保存
                with self.lock:
                    all_triples.extend(triples)
                    print(f"  [完成] {file_name} -> 提取 {len(triples)} 条，总计 {len(all_triples)} 条")
                    
                    with open(output_file, "w", encoding="utf-8") as out:
                        json.dump(all_triples, out, ensure_ascii=False, indent=2)
                        
            except Exception as e:
                print(f"  [错误] {file_name}: {e}")

        # 使用线程池加速
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            executor.map(task, to_process)
            
        print(f"\n✅ 并发抽取任务结束！保存至: {output_file}")

if __name__ == "__main__":
    extractor = SemanticExtractor()
    # 默认使用 8 个线程以大幅加速
    extractor.batch_process(max_workers=8)
