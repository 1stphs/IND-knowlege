import os
from openai import OpenAI
from dotenv import load_dotenv
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import json

import jieba

load_dotenv()

class SimilarityAnalyzer:
    def __init__(self, analyzer):
        self.analyzer = analyzer
        self.client = None
        api_key = os.getenv("API_KEY")
        base_url = os.getenv("BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("MODEL_NAME", "gpt-4o")
        
        if api_key:
            self.client = OpenAI(api_key=api_key, base_url=base_url)

    def calculate_tfidf_similarity(self, documents_text):
        if not documents_text:
            return np.array([])
        
        vectorizer = TfidfVectorizer()
        corpus = []
        for text in documents_text:
            words = jieba.cut(self.analyzer.clean_text(text))
            corpus.append(" ".join([w for w in words if len(w) > 1 and w not in self.analyzer.stop_words]))
            
        tfidf_matrix = vectorizer.fit_transform(corpus)
        return cosine_similarity(tfidf_matrix)

    def get_ai_semantic_relationship(self, doc1_info, doc2_info):
        """
        doc_info: {filename, keywords, snippet}
        """
        if not self.client:
            return None, "API Key not configured"

        prompt = f"""
请分析以下两个文件在语义逻辑上是否存在关联。
已知信息：
文件1: {doc1_info['filename']}
关键词1: {', '.join([k[0] for k in doc1_info['keywords']])}
内容片段1: {doc1_info['snippet']}

文件2: {doc2_info['filename']}
关键词2: {', '.join([k[0] for k in doc2_info['keywords']])}
内容片段2: {doc2_info['snippet']}

请判断它们是否讨论了相同、相关或互补的主题。
请以 JSON 格式返回结果，包含两个字段：
1. score: 0 到 1 之间的浮点数，代表相关度。
2. reason: 简短的理由（不超过50字）。
"""
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个专业的文档分析专家，擅长从文件名、关键词和片段中提取深层关联。"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            return float(result.get("score", 0)), result.get("reason", "")
        except Exception as e:
            print(f"AI Analysis Error: {e}")
            return None, str(e)
