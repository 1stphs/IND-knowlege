import os
import sys
import argparse
import json
import re
from dotenv import load_dotenv

# 加载环境变量，必须在引入其他模块前优先加载，确保全局生效
load_dotenv()

from analyzer import TextAnalyzer
from similarity_analyzer import SimilarityAnalyzer
from graph_builder import GraphBuilder

from extractors_mineru.mineru import (
    request_batch_upload_urls,
    upload_files_to_urls,
    poll_and_save_batch_results
)
from extractors_mineru.summarize_agent import (
    _summarize_with_fallback,
    _read_text,
    _write_text,
    _should_skip,
    _build_input_text
)

def _sanitize_for_json(text):
    """确保文本可以安全地作为 JSON 键或在 HTML 中显示，移除特殊字符"""
    if not text:
        return "Unknown"
    # 移除非字母数字字符，仅保留中文、字母、数字、点和下划线
    return re.sub(r'[^\w\u4e00-\u9fa5\.\-\s]', '_', str(text))

def _generate_summary_for_md(md_path: str, summary_path: str) -> str:
    """Uses summarize_agent's logic to generate a summary."""
    # Read environment variables set in .env
    base_url = os.getenv("OPENVIKING_LLM_API_BASE", os.getenv("OPENAI_BASE_URL", "https://aihubmix.com/v1"))
    model = os.getenv("OPENVIKING_LLM_MODEL", os.getenv("OPENAI_MODEL", "grok-4-fast-non-reasoning"))
    provider = os.getenv("OPENVIKING_LLM_PROVIDER", os.getenv("SUMMARY_PROVIDER", "auto"))
    api_key = (
        str(os.getenv("OPENVIKING_LLM_API_KEY", "")).strip()
        or str(os.getenv("OPENVIKING_API_KEY", "")).strip()
        or str(os.getenv("OPENAI_API_KEY", "")).strip()
    )
    if not api_key:
        api_key = os.getenv("API_KEY", "")

    if api_key.lower().startswith("bearer "):
        api_key = api_key.strip()
    
    if _should_skip(md_path, summary_path, force=False):
        try:
            content = _read_text(summary_path)
            # 简单剥离标题
            return content.split("\n\n", 1)[-1].strip()
        except:
            pass

    try:
        md_text = _read_text(md_path)
        prompt_text = _build_input_text(md_text, max_chars=14000)
        
        # 增加基于内容长度的动态 Prompt
        content_len = len(md_text)
        if content_len < 800:
            instruction = f"请为下面的 Markdown 文档撰写一个极其简短精炼的摘要（约100字，只需1-2句话）：\n\n{prompt_text}"
            target_tokens = 150
        else:
            instruction = f"请为下面的 Markdown 文档撰写一个简要的学术总结（约300字）：\n\n{prompt_text}"
            target_tokens = 400
        
        summary = _summarize_with_fallback(
            base_url=base_url,
            api_key=api_key,
            model=model,
            max_tokens=target_tokens,
            text=instruction,
            provider=provider,
        )
        
        title = os.path.basename(md_path)
        out = f"# {title} 摘要\n\n{summary.strip()}\n"
        print(f"\n[{title} 摘要]: {summary[:80].strip()}...\n")
        
        _write_text(summary_path, out)
        return summary.strip()
    except Exception as e:
        print(f"Summary extraction API failed: {e}")
        raise e


def main():
    parser = argparse.ArgumentParser(description="Document Knowledge Graph Generator")
    parser.add_argument("--dir", type=str, required=True, help="Directory containing documents")
    parser.add_argument("--output", type=str, default="output", help="Output directory")
    args = parser.parse_args()
    
    # Initialize components
    analyzer = TextAnalyzer()
    sim_analyzer = SimilarityAnalyzer(analyzer)
    graph_builder = GraphBuilder(args.output)
    
    # 1. Scan Files
    supported_exts = ['.pdf', '.docx', '.doc', '.xlsx']
    
    print(f"Scanning directory: {args.dir}")
    all_files = []
    for root, dirs, files in os.walk(args.dir):
        for f in files:
            if os.path.splitext(f)[1].lower() in supported_exts:
                all_files.append(os.path.join(root, f))
    
    if not all_files:
        print("No supported files found.")
        return

    # 2. Process with MinerU (Batch)
    os.makedirs(args.output, exist_ok=True)
    miner_dir = os.path.join(args.output, "mineru_markdowns")
    os.makedirs(miner_dir, exist_ok=True)
    
    # Check for existing results to determine which files need extraction
    files_to_extract = []
    saved_md_paths = []
    
    for f_path in all_files:
        base_name = os.path.basename(f_path)
        # MinerU usually outputs .md with the same base name (ignoring original extension)
        # Or it might append .md to the full filename. Let's be safe.
        stem = os.path.splitext(base_name)[0]
        potential_md = os.path.join(miner_dir, f"{stem}.md")
        
        if os.path.exists(potential_md):
            saved_md_paths.append(potential_md)
        else:
            files_to_extract.append(f_path)
    
    if files_to_extract:
        print(f"MinerU batch extracting {len(files_to_extract)} new/remaining files...")
        try:
            batch_id, upload_urls = request_batch_upload_urls(file_names=files_to_extract)
            upload_files_to_urls(files_to_extract, upload_urls)
            newly_saved = poll_and_save_batch_results(batch_id, output_dir=miner_dir)
            saved_md_paths.extend(newly_saved)
        except Exception as e:
            print(f"MinerU extraction failed: {e}")
            if not saved_md_paths: return

    if not saved_md_paths:
        print("No markdown files available to process.")
        return

    documents = []

    # 3. Process the extracted markdown files
    for md_path in saved_md_paths:
        if not md_path or not os.path.exists(md_path): continue
        
        base_name = os.path.basename(md_path)
        stem = base_name[:-3] if base_name.lower().endswith(".md") else base_name
        # 清理文件名逻辑，确保在 JSON 字典中作为键时不会出错
        safe_name = _sanitize_for_json(stem)
        
        summary_path = os.path.join(miner_dir, f"{stem}.summary.md")
        
        print(f"Processing: {safe_name}...")
        
        # 提取内容
        try:
            content = _read_text(md_path)
        except:
            continue
            
        if not content.strip(): continue

        # 生成摘要
        try:
            snippet = _generate_summary_for_md(md_path, summary_path)
        except:
            snippet = analyzer.get_summary_snippet(content, max_len=500)
            
        keywords = analyzer.get_keywords(content, top_k=10)
        hf_words = analyzer.get_high_freq_words(content, top_k=15)
        
        doc_data = {
            "filename": safe_name,
            "content": content,
            "keywords": keywords,
            "hf_words": hf_words,
            "snippet": snippet
        }
        documents.append(doc_data)
        
        print(f"Generating individual graph for {safe_name}...")
        graph_builder.build_individual_graph(safe_name, keywords, hf_words)

    if len(documents) < 2:
        print("Need at least 2 documents for global analysis.")
        return

    # 4. Global Similarity
    print("Calculating TF-IDF similarities...")
    content_list = [doc["content"] for doc in documents]
    sim_matrix = sim_analyzer.calculate_tfidf_similarity([doc for doc in content_list])
    
    file_similarities = {}
    potential_pairs = []
    
    count = len(documents)
    for i in range(count):
        for j in range(i + 1, count):
            score = float(sim_matrix[i][j])
            file_similarities[(documents[i]["filename"], documents[j]["filename"])] = score
            if score > 0.15:
                potential_pairs.append((i, j))

    # 5. AI Semantic
    ai_relationships = {}
    if os.getenv("API_KEY"):
        print(f"Refining {len(potential_pairs)} relationships with AI...")
        for i, j in potential_pairs:
            f1, f2 = documents[i]["filename"], documents[j]["filename"]
            try:
                score, reason = sim_analyzer.get_ai_semantic_relationship(documents[i], documents[j])
                ai_relationships[(f1, f2)] = (float(score) if score is not None else 0.0, _sanitize_for_json(reason))
            except:
                continue

    # 6. Global Graph
    print("Generating global graph...")
    graph_builder.build_global_graph(file_similarities, ai_relationships)
    
    print(f"\nDone! Results are in '{args.output}'.")

if __name__ == "__main__":
    main()
