import os
import sys
import json
import logging
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.foxuai_client import NocoBaseClient

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def debug_parent_and_fields():
    client = NocoBaseClient()
    
    # 子表 ID (来自之前的 record_debug.json)
    child_id = "355253199372288"
    
    logger.info(f"正在获取子表记录 {child_id}...")
    child_record = client.get_record("ind_knowledge_files", child_id)
    parent_id = child_record.get("ind_knowledge_id")
    
    logger.info(f"父表 ID: {parent_id}")
    
    logger.info(f"正在获取父表记录 {parent_id}...")
    parent_record = client.get_record("ind_knowledge", parent_id)
    
    # 打印父表的所有键
    logger.info(f"父表字段: {sorted(parent_record.keys())}")
    
    # 检查是否有关键字或摘要相关的字段
    potential_fields = [k for k in parent_record.keys() if any(x in k.lower() for x in ["key", "sum", "summary", "keyword", "desc", "f_"])]
    logger.info(f"潜在相关字段 (父表): {potential_fields}")
    
    # 打印子表的所有键
    logger.info(f"子表字段: {sorted(child_record.keys())}")
    potential_child_fields = [k for k in child_record.keys() if any(x in k.lower() for x in ["key", "sum", "summary", "keyword", "desc", "f_"])]
    logger.info(f"潜在相关字段 (子表): {potential_child_fields}")

    # 将详细数据保存到文件
    with open("full_debug_data.json", "w", encoding="utf-8") as f:
        json.dump({
            "child": child_record,
            "parent": parent_record
        }, f, indent=2, ensure_ascii=False)
    
    logger.info("调试数据已保存到 full_debug_data.json")

if __name__ == "__main__":
    debug_parent_and_fields()
