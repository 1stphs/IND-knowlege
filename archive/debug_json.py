import os
import json
import re

# 模拟相似度数据
file_similarities = {
    ("2.3.P.1-剂型及产品组成-正大天晴药业集团南京顺欣制药有限公司", "2.3.P.2-产品开发-正大天晴药业集团南京顺欣制药有限公司"): 0.8
}

try:
    print("Testing basic serialization...")
    json.dumps(file_similarities)
    print("Success!")
except Exception as e:
    print(f"Failed basic serialization: {e}")

# 模拟包含元组键的字典转换为列表（pyvis 内部可能会做的事情）
try:
    print("Testing tuple-key conversion...")
    items = list(file_similarities.items())
    print(f"Items: {items}")
    # pyvis 在 add_edge 时会处理这些，但如果是转 JSON 则会失败
    json.dumps({str(k): v for k, v in file_similarities.items()})
    print("Success with stringified keys!")
except Exception as e:
    print(f"Failed: {e}")
