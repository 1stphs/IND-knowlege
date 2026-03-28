import jieba
import jieba.analyse
from collections import Counter
import re

class TextAnalyzer:
    def __init__(self, stop_words_path=None):
        self.stop_words = set()
        if stop_words_path:
            self.load_stop_words(stop_words_path)
        else:
            # Basic default stop words
            self.stop_words = {"的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好", "自己", "这"}

    def load_stop_words(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    self.stop_words.add(line.strip())
        except Exception as e:
            print(f"Error loading stop words: {e}")

    def clean_text(self, text):
        # Remove non-alphanumeric characters except basic punctuation if needed
        text = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', ' ', text)
        return text

    def get_keywords(self, text, top_k=10):
        # Using TF-IDF via jieba
        keywords = jieba.analyse.extract_tags(text, topK=top_k, withWeight=True)
        return keywords

    def get_high_freq_words(self, text, top_k=20):
        words = jieba.cut(text)
        filtered_words = [word for word in words if len(word) > 1 and word not in self.stop_words and not word.isspace()]
        counter = Counter(filtered_words)
        return counter.most_common(top_k)

    def get_summary_snippet(self, text, max_len=500):
        # Simply take the first part of the cleaned text as a snippet
        cleaned = re.sub(r'\s+', ' ', text).strip()
        return cleaned[:max_len]
