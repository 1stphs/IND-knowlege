import os
import sys
import json
import logging
import re
from pathlib import Path
from dotenv import load_dotenv

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.foxuai_client import NocoBaseClient
from analyzer import TextAnalyzer

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def discover_keyword_field(client: NocoBaseClient) -> str:
    """尝试自动探测关键词的真实字段名"""
    # 用户已确认在子表添加了名为 keywords 的字段
    return "keywords"

def sync_backfill_to_foxuai(mineru_dir: str = "output/mineru_markdowns", dry_run: bool = False):
    """
    将本地生成的解析内容、摘要、关键词回传至 FoxUAI。
    """
    load_dotenv()
    client = NocoBaseClient()
    analyzer = TextAnalyzer()
    
    if not os.path.exists(mineru_dir):
        logger.error(f"处理结果目录不存在: {mineru_dir}")
        return
        
    keyword_field_name = discover_keyword_field(client)
    logger.info(f"使用映射: 摘要->summary, 内容->extracted_content, 文件名->field_name, 关键词->{keyword_field_name}")
    
    # 预先获取 FoxUAI 子表数据，用于精确匹配
    foxuai_records = {} # id -> record
    foxuai_title_map = {} # field_name / title -> id
    try:
        page = 1
        logger.info("正在获取 FoxUAI 现有文件记录用于智能匹配...")
        while True:
            resp = client.list_records("ind_knowledge_files", params={"pageSize": 100, "page": page, "appends": ["file"]})
            data = resp.get("data", [])
            for row in data:
                row_id = str(row.get("id"))
                foxuai_records[row_id] = row
                
                # 从关联的文件附件中尝试获取原名
                attachments = row.get("file")
                f_name = None
                if attachments:
                    if isinstance(attachments, dict): attachments = [attachments]
                    if len(attachments) > 0:
                        att = attachments[0]
                        f_name = att.get("title")
                        if not f_name and att.get("filename"):
                            f_name = os.path.splitext(att.get("filename"))[0]
                            
                # Fallback 到子表本身的 field_name
                if not f_name:
                    f_name = row.get("field_name")
                    
                if f_name:
                    foxuai_title_map[f_name] = row_id
                    
            if len(data) < 100:
                break
            page += 1
        logger.info(f"成功获取 {len(foxuai_records)} 条线上文件记录信息。")
    except Exception as e:
        logger.warning(f"获取全量记录失败，将回退到正则表达式匹配 ID 模式: {e}")

    md_files = [f for f in os.listdir(mineru_dir) if f.endswith(".md") and not f.endswith(".summary.md")]
    logger.info(f"发现在 {mineru_dir} 目录下的 {len(md_files)} 个 Markdown 文档")
    
    success_count = 0
    fail_count = 0
    
    for md_filename in md_files:
        stem = md_filename[:-3]
        record_id = None
        
        # 匹配策略 1: 完全按文件名或 stem 匹配 title_map
        if stem in foxuai_title_map:
            record_id = foxuai_title_map[stem]
        else:
            # 匹配策略 2: 文件名前缀 `{id}_` 匹配
            match = re.match(r"^(\d+)_", md_filename)
            if match:
                extracted_id = match.group(1)
                # 验证是否真的是合法的 FoxUAI ID (而不是像 1.0_xxx 这种)
                if foxuai_records and extracted_id in foxuai_records:
                    record_id = extracted_id
                elif not foxuai_records: # API失败时的退路
                    record_id = extracted_id
                    
        if not record_id:
            logger.info(f"跳过文件 {md_filename}: 无法在 FoxUAI 记录中找到匹配的 ID 或文件名")
            continue
            
        md_path = os.path.join(mineru_dir, md_filename)
        try:
            with open(md_path, "r", encoding="utf-8") as f:
                extracted_content = f.read()
        except Exception as e:
            logger.error(f"无法读取文件 {md_path}: {e}")
            fail_count += 1
            continue
            
        # 读取摘要
        # 根据 main.py，摘要保存在 {stem}.summary.md
        stem = md_filename[:-3]
        summary_path = os.path.join(mineru_dir, f"{stem}.summary.md")
        summary_content = ""
        if os.path.exists(summary_path):
            try:
                with open(summary_path, "r", encoding="utf-8") as f:
                    summary_content = f.read()
            except Exception as e:
                logger.warning(f"无法读取摘要 {summary_path}: {e}")
        else:
            # Fallback 粗略摘要
            summary_content = analyzer.get_summary_snippet(extracted_content, max_len=500)
            
        # 生成关键词
        # 实时生成关键词，避免复杂的 JSON 缓存读取
        keywords_list = analyzer.get_keywords(extracted_content, top_k=10)
        # NocoBase JSON 字段需要数组格式
        keywords_json = [word for word, weight in keywords_list]
        
        # 构造更新载荷
        update_payload = {
            "extracted_content": extracted_content,
            "summary": summary_content,
            "field_name": stem, # 提取无后缀名
            "keywords": keywords_json  # 传入列表，httpx 会自动序列化为 JSON
        }
        
        logger.info(f"准备更新记录 ID: {record_id}，文件: {stem}")
        
        if dry_run:
            logger.info("[Dry Run] 更新内容预览:")
            logger.info(f"  Field Name: {stem}")
            logger.info(f"  Keywords: {keywords_json}")
            logger.info(f"  Summary 首句: {summary_content[:50]}...")
            success_count += 1
            continue
            
        try:
            client.update_record("ind_knowledge_files", record_id, update_payload)
            logger.info(f"✅ 更新成功: 子表 ID {record_id}")
            success_count += 1
        except Exception as e:
            logger.error(f"❌ 更新失败: 子表 ID {record_id}, 错误: {e}")
            fail_count += 1
            
    logger.info(f"回传完成。成功: {success_count}, 失败: {fail_count}")

if __name__ == "__main__":
    # 支持传入 --dry-run 参数测试
    is_dry_run = "--dry-run" in sys.argv
    target_dir = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "output/mineru_markdowns"
    sync_backfill_to_foxuai(target_dir, dry_run=is_dry_run)
