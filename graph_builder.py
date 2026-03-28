import os
from pyvis.network import Network
import networkx as nx

class GraphBuilder:
    def __init__(self, output_dir="output"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def _configure_layout(self, net: Network):
        """
        通过物理引擎参数控制布局，增加间距。
        """
        # 显著增强斥力，增加弹簧长度
        net.barnes_hut(
            gravity=-25000,          # 极强斥力
            central_gravity=0.1,     # 弱向心力
            spring_length=450,       # 长连线
            spring_strength=0.05,    # 较强刚性
            damping=0.09
        )

    def build_individual_graph(self, filename, keywords, high_freq_words):
        """
        Create a graph for a single file.
        """
        net = Network(height="800px", width="100%", bgcolor="#FFFFFF", font_color="#333333", notebook=False)
        self._configure_layout(net)
        
        # 节点属性：简约风
        # 将字体上移防止遮挡
        font_style = {"size": 16, "face": "Arial", "vadjust": -35}
        
        net.add_node(filename, label=filename, title=f"File: {filename}", color="#2B5B84", size=25, shape="dot", font=font_style)
        
        for word, weight in keywords:
            net.add_node(word, label=word, title=f"Keyword (Weight: {weight:.2f})", color="#619CFF", size=18, font={"size": 14})
            net.add_edge(filename, word, value=weight, color="#D4E6F1")
            
        for word, count in high_freq_words:
            if word not in net.get_nodes():
                net.add_node(word, label=word, title=f"High Freq (Count: {count})", color="#AEC7E8", size=12, font={"size": 12})
            net.add_edge(filename, word, value=count/max(1, count), color="#D4E6F1")

        output_path = os.path.join(self.output_dir, f"graph_{filename}.html")
        net.save_graph(output_path)
        return output_path

    def build_global_graph(self, file_similarities, ai_relationships=None):
        """
        Create a global graph showing relationships between files.
        """
        net = Network(height="900px", width="100%", bgcolor="#FFFFFF", font_color="#333333", notebook=False)
        self._configure_layout(net)
        
        files = set()
        for f1, f2 in file_similarities.keys():
            files.add(f1)
            files.add(f2)
            
        font_style = {"size": 14, "face": "Arial", "vadjust": -40}
            
        for f in files:
            net.add_node(f, label=f, title=f, color="#2B5B84", size=20, font=font_style)
            
        for (f1, f2), score in file_similarities.items():
            if score > 0.15: 
                title = f"TF-IDF Similarity: {score:.2f}"
                value = score * 6
                
                edge_color = "#D4E6F1"
                
                if ai_relationships and (f1, f2) in ai_relationships:
                    ai_score, reason = ai_relationships[(f1, f2)]
                    if ai_score and ai_score >= 0.2:
                        title += f"\\nAI Score: {ai_score:.2f}\\n{reason}"
                        value = (score + ai_score) * 5
                        edge_color = "#85C1E9" # 稍微加深一点连线颜色
                
                net.add_edge(f1, f2, value=value, title=title, color=edge_color)

        output_path = os.path.join(self.output_dir, "global_relationship_graph.html")
        net.save_graph(output_path)
        return output_path
