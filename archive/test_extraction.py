from semantic_extractor import SemanticExtractor
import json
import os

def test_single_file():
    # 初始化抽取器
    extractor = SemanticExtractor(schema_path="ontology/ind_schema.json")
    
    # 选择测试文件
    test_file = "output/mineru_markdowns/2.3.P.1-剂型及产品组成-正大天晴药业集团南京顺欣制药有限公司.md"
    
    if not os.path.exists(test_file):
        print(f"Error: {test_file} 不存在")
        return

    # 执行抽取
    print(f"开始对 {test_file} 进行测试抽取...")
    triples = extractor.extract_from_file(test_file)
    
    # 结果展示
    print(f"\n抽取完成！共获得 {len(triples)} 条三元组。")
    
    output_test = "ontology/test_triples_1.8.3.json"
    with open(output_test, "w", encoding="utf-8") as f:
        json.dump(triples, f, ensure_ascii=False, indent=2)
        
    print(f"测试结果已保存至: {output_test}")
    
    # 打印前 5 条作为预览
    for i, t in enumerate(triples[:5]):
        print(f"[{i+1}] {t.get('subject', 'N/A')} --({t.get('predicate', 'N/A')})--> {t.get('object', 'N/A')}")

if __name__ == "__main__":
    test_single_file()
