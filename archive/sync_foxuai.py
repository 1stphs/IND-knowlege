import os
import sys
import json
import logging
from pathlib import Path

# 添加当前目录到路径，确保能引入 lib
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.foxuai_client import NocoBaseClient

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def sync_foxuai_knowledge(output_dir: str = "input_subset/foxuai_docs"):
    """
    从 FoxUAI 同步 IND 知识库文件。
    """
    client = NocoBaseClient()
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info("开始从 FoxUAI 获取知识库主表...")
    try:
        # 1. 获取知识库主表 (ind_knowledge)
        knowledge_resp = client.list_records("ind_knowledge")
        knowledge_items = knowledge_resp.get("data", [])
        
        logger.info(f"获取到 {len(knowledge_items)} 条知识库记录。")
        
        for item in knowledge_items:
            k_id = item.get("id")
            title = item.get("title", f"knowledge_{k_id}")
            logger.info(f"正在处理: {title} (ID: {k_id})")
            
            # 2. 获取该条目下的文件列表 (ind_knowledge_files:list)
            # 根据文档，路径为 ind_knowledge/{id}/ind_knowledge_files:list
            # NocoBase 必须带上 appends=['file'] 才能获取到附件对象
            files_path = f"ind_knowledge/{k_id}/ind_knowledge_files"
            files_resp = client.list_records(files_path, params={
                "appends": ["file"]
            })
            files_data = files_resp.get("data", [])
            
            logger.info(f"  找到 {len(files_data)} 个关联文件。")
            
            for f_item in files_data:
                # 附件字段名为 'file'，包含 'url' 和 'filename'
                # 兼容单一附件和多个附件的情况
                attachments = f_item.get("file")
                if not attachments:
                    continue
                
                # 如果是单个附件对象，转成列表处理
                if isinstance(attachments, dict):
                    attachments = [attachments]
                
                for file_info in attachments:
                    if isinstance(file_info, dict) and (file_info.get("url") or file_info.get("path")):
                        file_url = file_info.get("url") or file_info.get("path")
                        file_name = file_info.get("filename") or file_info.get("title") or f"file_{f_item.get('id')}.pdf"
                        
                        # 避免同名文件覆盖
                        target_path = os.path.join(output_dir, f"{k_id}_{file_name}")
                        
                        if not os.path.exists(target_path):
                            logger.info(f"    正在下载: {file_name}")
                            try:
                                client.download_file(file_url, target_path)
                                logger.info(f"    下载成功: {target_path}")
                            except Exception as e:
                                logger.error(f"    下载失败: {file_name}, 错误: {e}")
                        else:
                            logger.info(f"    文件已存在，跳过: {file_name}")
                    else:
                        logger.warning(f"    无法识别文件结构: {json.dumps(file_info)[:100]}...")

    except Exception as e:
        logger.error(f"同步过程中发生错误: {e}")
        raise

if __name__ == "__main__":
    # 解析命令行参数或直接运行
    target_dir = sys.argv[1] if len(sys.argv) > 1 else "input_subset/foxuai_docs"
    sync_foxuai_knowledge(target_dir)
