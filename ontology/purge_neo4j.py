from neo4j import GraphDatabase
import os
from dotenv import load_dotenv

load_dotenv()

def purge():
    uri = os.getenv("NEO4J_URI")
    user = os.getenv("NEO4J_USER")
    password = os.getenv("NEO4J_PASSWORD")
    
    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        print("Purging database...")
        session.run("MATCH (n) DETACH DELETE n")
        print("Done.")
    driver.close()

if __name__ == "__main__":
    purge()
