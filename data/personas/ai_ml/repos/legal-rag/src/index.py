# project: legal-rag (synthetic)
import os, json
from pinecone import Pinecone
pc = Pinecone(api_key=os.environ['PINECONE_KEY'])
index = pc.Index('chunks')

def upsert(chunks, vectors):
    index.upsert(vectors=[(c.id, v, c.meta) for c, v in zip(chunks, vectors)])
