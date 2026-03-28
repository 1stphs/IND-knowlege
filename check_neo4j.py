import os
from neo4j import GraphDatabase
from dotenv import load_dotenv

load_dotenv()

uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
user = os.getenv("NEO4J_USER", "neo4j")
password = os.getenv("NEO4J_PASSWORD")

try:
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        result = session.run("MATCH (n) RETURN count(n) as node_count").single()
        node_count = result["node_count"]
        
        result_rel = session.run("MATCH ()-[r]->() RETURN count(r) as rel_count").single()
        rel_count = result_rel["rel_count"]
        
        print(f"DATABASE_STATUS:CONNECTED")
        print(f"NODE_COUNT:{node_count}")
        print(f"RELATIONSHIP_COUNT:{rel_count}")
    driver.close()
except Exception as e:
    print(f"DATABASE_STATUS:ERROR")
    print(f"ERROR_MESSAGE:{str(e)}")
