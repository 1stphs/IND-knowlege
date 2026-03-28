import os
import json
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

class TriplesToNeo4j:
    def __init__(self):
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self):
        self.driver.close()

    def create_constraints(self):
        with self.driver.session() as session:
            # Create constraints for unique IDs
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Class) REQUIRE c.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (d:Document) REQUIRE d.document_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (ch:Chunk) REQUIRE ch.chunk_id IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (ev:Evidence) REQUIRE ev.evidence_id IS UNIQUE")
            print("Constraints created.")

    def ingest_tbox(self, schema_file="ontology/ind_schema.json"):
        if not os.path.exists(schema_file):
            print(f"TBox file {schema_file} not found.")
            return

        with open(schema_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            schema = data.get("ontology", {})

        def process_classes(classes, parent_id=None):
            with self.driver.session() as session:
                for cls in classes:
                    # Case 1: cls is a string (leaf subclass)
                    if isinstance(cls, str):
                        cls_id = cls
                        cls_desc = ""
                        subclasses = []
                    # Case 2: cls is a dict
                    else:
                        cls_id = cls.get("id")
                        cls_desc = cls.get("description", "")
                        subclasses = cls.get("subclasses", [])

                    if not cls_id: continue

                    # Create Class node
                    session.run("""
                        MERGE (c:Class {id: $id})
                        SET c.name = $id,
                            c.description = $description
                    """, id=cls_id, description=cls_desc)
                    print(f"  Class created: {cls_id}")

                    # Create SUBCLASS_OF relationship
                    if parent_id:
                        session.run("""
                            MATCH (child:Class {id: $c_id}), (parent:Class {id: $p_id})
                            MERGE (child)-[:SUBCLASS_OF]->(parent)
                        """, c_id=cls_id, p_id=parent_id)

                    # Recurse
                    if subclasses:
                        process_classes(subclasses, parent_id=cls_id)

        print("Ingesting TBox classes...")
        process_classes(schema.get("classes", []))
        print("TBox ingestion complete.")

    def ingest_abox(self, triples_file: str):
        """
        向 Neo4j 写入 ABox 事实。
        """
        if not os.path.exists(triples_file):
            print(f"File not found: {triples_file}")
            return
            
        with open(triples_file, "r", encoding="utf-8") as f:
            triples = json.load(f)
            
        print(f"Ingesting {len(triples)} ABox triples...")
        
        with self.driver.session() as session:
            count = 0
            for t in triples:
                # 处理嵌套对象的情况
                def get_entity_info(item):
                    if not item: return "Unknown", "Entity"
                    if isinstance(item, dict):
                        # 如果是字典，提取 id，如果没有 id 则取首个键值对或整体字符串
                        eid = item.get("id") or item.get("name") or str(item)
                        etype = item.get("type") or item.get("subclass") or "Entity"
                        return str(eid).strip(), str(etype).strip()
                    return str(item).strip(), "Entity"

                sub_id, sub_type = get_entity_info(t.get("subject"))
                obj_id, obj_type = get_entity_info(t.get("object"))
                pred = str(t.get("predicate") or "RELATED").strip()
                document_id = str(t.get("document_id") or t.get("source_md") or "unknown").strip()
                chunk_id = str(t.get("chunk_id") or "unknown_chunk").strip()
                evidence_id = str(t.get("evidence_id") or f"ev_{chunk_id}").strip()
                source_md = str(t.get("source_md", "unknown"))
                source_location = str(t.get("source_location", "unknown"))
                source_context = str(t.get("source_context", ""))
                
                # 过滤明显过长的 ID (可能是脏数据)
                if len(sub_id) > 100 or len(obj_id) > 100:
                    continue
                if not sub_id or not obj_id:
                    continue

                try:
                    # 创建主体节点
                    session.run("""
                        MERGE (s:Entity {id: $id})
                        ON CREATE SET s.type = $type
                    """, id=sub_id, type=sub_type)
                    
                    # 创建客体节点
                    session.run("""
                        MERGE (o:Entity {id: $id})
                        ON CREATE SET o.type = $type
                    """, id=obj_id, type=obj_type)
                    
                    # 创建关系 (包含溯源元数据)
                    pred = str(t["predicate"]).strip()
                    session.run("""
                        MATCH (s:Entity {id: $sub_id}), (o:Entity {id: $obj_id})
                        MERGE (d:Document {document_id: $document_id})
                        SET d.source_md = $src
                        MERGE (c:Chunk {chunk_id: $chunk_id})
                        SET c.document_id = $document_id,
                            c.source_md = $src,
                            c.source_location = $loc,
                            c.content = $ctx
                        MERGE (ev:Evidence {evidence_id: $evidence_id})
                        SET ev.document_id = $document_id,
                            ev.chunk_id = $chunk_id,
                            ev.source_md = $src,
                            ev.source_location = $loc,
                            ev.source_context = $ctx
                        MERGE (d)-[:HAS_CHUNK]->(c)
                        MERGE (c)-[:HAS_EVIDENCE]->(ev)
                        MERGE (s)-[r:RELATED {
                            relation_id: $relation_id
                        }]->(o)
                        SET r.original_predicate = $pred,
                            r.document_id = $document_id,
                            r.chunk_id = $chunk_id,
                            r.evidence_id = $evidence_id,
                            r.source_md = $src,
                            r.source_location = $loc,
                            r.source_context = $ctx
                    """, 
                    sub_id=sub_id, obj_id=obj_id, pred=pred,
                    document_id=document_id,
                    chunk_id=chunk_id,
                    evidence_id=evidence_id,
                    relation_id=f"{sub_id}:{pred}:{obj_id}:{chunk_id}",
                    src=source_md,
                    loc=source_location,
                    ctx=source_context
                    )
                    count += 1
                except Exception as e:
                    print(f"Error processing triple: {e}")

        print(f"Successfully ingested {count} ABox triples.")

if __name__ == "__main__":
    ingestor = TriplesToNeo4j()
    ingestor.create_constraints()
    # 1. 写入 TBox
    ingestor.ingest_tbox("ontology/ind_schema.json")
    # 2. 写入 ABox
    ingestor.ingest_abox("ontology/extracted_triples.json")
    ingestor.close()
