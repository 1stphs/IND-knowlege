import os
import glob
from pathlib import Path

def aggregate_summaries(input_dir="output/mineru_markdowns", output_file="output/aggregated_ind_summaries.md"):
    """
    聚合目录下所有的 .summary.md 文件，生成一个全景式摘要文档。
    """
    summary_files = glob.glob(os.path.join(input_dir, "*.summary.md"))
    summary_files.sort() # 保证顺序一致
    
    print(f"发现 {len(summary_files)} 个摘要文件，准备聚合...")
    
    aggregated_content = [
        "# IND 全量文档摘要聚合 (Wide-Coverage Discovery Source)\n",
        f"该文件聚合了 {len(summary_files)} 个分段文档的 AI 摘要，用于 TBox 本体发现与实体关联分析。\n",
        "---"
    ]
    
    for f_path in summary_files:
        base_name = os.path.basename(f_path)
        # 获取文件名（去掉 .summary.md）
        doc_name = base_name.replace(".summary.md", "")
        
        try:
            with open(f_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                # 移除原有的 # 标题，统一层级
                clean_content = content.replace(f"# {doc_name}.md 摘要", "")
                clean_content = clean_content.replace(f"# {doc_name} 摘要", "").strip()
                
                aggregated_content.append(f"\n## 文档标识: {doc_name}\n")
                aggregated_content.append(clean_content)
                aggregated_content.append("\n---\n")
        except Exception as e:
            print(f"读取 {f_path} 失败: {e}")
            
    # 写入结果
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as out:
        out.write("\n".join(aggregated_content))
    
    print(f"聚合完成！输出文件: {output_file} (总计 {len(aggregated_content)} 个区块)")
    return output_file

if __name__ == "__main__":
    aggregate_summaries()
