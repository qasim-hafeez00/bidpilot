"""Canonical skill taxonomy with surface-form aliases.

Used by (a) the data builder to map Upwork tags / text to canonical skills for GOLD labels and
(b) the Job Analyst's deterministic extractor. The portfolio's *implied* skills (visible only in
code imports) are deliberately NOT discoverable through these aliases in case-study prose, which
is what makes the corpus hard for naive retrieval.
"""
from __future__ import annotations

import re
from functools import lru_cache

# canonical -> aliases (lowercase). Canonical name itself is always an alias.
SKILLS: dict[str, list[str]] = {
    # --- languages / core
    "Python": ["python", "py3"],
    "JavaScript": ["javascript", "js", "es6"],
    "TypeScript": ["typescript", "ts"],
    "SQL": ["sql", "t-sql", "tsql", "pl/sql", "sql queries"],
    "R": ["r programming", "rstudio", "r language", "tidyverse"],
    "Go": ["golang"],
    "Java": ["java", "spring boot"],
    "PHP": ["php", "laravel", "wordpress"],
    # --- ML / AI
    "Machine Learning": ["machine learning", "ml model", "ml models", "predictive model", "predictive modeling"],
    "Deep Learning": ["deep learning", "neural network", "neural networks"],
    "PyTorch": ["pytorch", "torch"],
    "TensorFlow": ["tensorflow", "keras"],
    "scikit-learn": ["scikit-learn", "sklearn", "scikit learn"],
    "NLP": ["nlp", "natural language processing", "text classification", "named entity", "sentiment analysis"],
    "LLM": ["llm", "llms", "large language model", "gpt-4", "gpt4", "openai api", "chatgpt api", "llama", "mistral"],
    "RAG": ["rag", "retrieval augmented", "retrieval-augmented", "knowledge base chatbot"],
    "LangChain": ["langchain", "langgraph", "llamaindex", "llama index"],
    "Prompt Engineering": ["prompt engineering", "prompt design"],
    "Fine-tuning": ["fine-tuning", "fine tuning", "finetuning", "lora", "qlora"],
    "Computer Vision": ["computer vision", "image classification", "object detection", "image segmentation"],
    "OpenCV": ["opencv", "cv2"],
    "YOLO": ["yolo", "yolov5", "yolov8", "ultralytics"],
    "Hugging Face": ["hugging face", "huggingface", "transformers library"],
    "Vector Database": ["vector database", "vector db", "pinecone", "chroma", "chromadb", "weaviate", "qdrant", "faiss", "pgvector"],
    "MLOps": ["mlops", "model deployment", "model serving"],
    "MLflow": ["mlflow"],
    "Time Series Forecasting": ["time series", "forecasting", "arima", "prophet"],
    "Recommendation Systems": ["recommendation system", "recommender", "recommendation engine"],
    "Chatbot": ["chatbot", "chat bot", "conversational ai", "ai assistant"],
    "Speech Recognition": ["speech recognition", "speech-to-text", "whisper", "asr"],
    "AWS SageMaker": ["sagemaker"],
    # --- web
    "React": ["react", "react.js", "reactjs"],
    "Next.js": ["next.js", "nextjs"],
    "Vue.js": ["vue", "vue.js", "vuejs", "nuxt"],
    "Angular": ["angular"],
    "Node.js": ["node.js", "nodejs", "node js"],
    "Express": ["express.js", "expressjs"],
    "Django": ["django"],
    "Django REST Framework": ["django rest framework", "drf"],
    "Flask": ["flask"],
    "FastAPI": ["fastapi"],
    "REST API": ["rest api", "restful", "api development", "api integration", "rest apis"],
    "GraphQL": ["graphql", "apollo"],
    "PostgreSQL": ["postgresql", "postgres"],
    "MySQL": ["mysql", "mariadb"],
    "MongoDB": ["mongodb", "mongo", "mongoose"],
    "Redis": ["redis"],
    "Celery": ["celery"],
    "Docker": ["docker", "containerization", "docker-compose", "docker compose"],
    "Kubernetes": ["kubernetes", "k8s"],
    "AWS": ["aws", "amazon web services", "ec2", "s3", "lambda"],
    "GCP": ["gcp", "google cloud"],
    "Azure": ["azure"],
    "CI/CD": ["ci/cd", "github actions", "gitlab ci", "jenkins"],
    "Tailwind CSS": ["tailwind", "tailwindcss"],
    "HTML/CSS": ["html", "css", "html5", "css3", "sass"],
    "Stripe": ["stripe", "payment gateway", "payment integration"],
    "WebSockets": ["websocket", "websockets", "socket.io", "real-time"],
    "Authentication": ["oauth", "jwt", "authentication", "auth0", "sso"],
    "Firebase": ["firebase", "firestore"],
    "Web Scraping": ["web scraping", "scraper", "scrapy", "beautifulsoup", "selenium"],
    "Shopify": ["shopify"],
    "React Native": ["react native"],
    "Flutter": ["flutter", "dart"],
    # --- data / BI
    "pandas": ["pandas", "dataframe"],
    "NumPy": ["numpy"],
    "Excel": ["excel", "vba", "spreadsheet", "pivot table", "pivot tables", "xlookup", "vlookup"],
    "Google Sheets": ["google sheets", "apps script"],
    "Power BI": ["power bi", "powerbi", "power query"],
    "DAX": ["dax"],
    "Tableau": ["tableau"],
    "Looker Studio": ["looker studio", "data studio", "looker"],
    "dbt": ["dbt", "data build tool"],
    "Snowflake": ["snowflake"],
    "BigQuery": ["bigquery", "big query"],
    "Airflow": ["airflow", "dag orchestration"],
    "ETL": ["etl", "elt", "data pipeline", "data pipelines", "data integration"],
    "Data Visualization": ["data visualization", "data visualisation", "dashboard", "dashboards", "charts"],
    "Statistics": ["statistics", "statistical analysis", "regression analysis", "hypothesis testing", "spss"],
    "A/B Testing": ["a/b test", "a/b testing", "ab testing", "experimentation"],
    "Data Cleaning": ["data cleaning", "data cleansing", "data wrangling", "data entry cleanup"],
    "Google Analytics": ["google analytics", "ga4"],
    "Data Analysis": ["data analysis", "data analytics", "exploratory data analysis", "eda", "analyze data"],
    "KPI Reporting": ["kpi", "kpis", "reporting", "business intelligence", "bi reports"],
    # --- off-domain (for skip jobs)
    "Social Media Marketing": ["social media marketing", "instagram growth", "tiktok marketing", "facebook ads"],
    "SEO": ["seo", "search engine optimization"],
    "Graphic Design": ["graphic design", "logo design", "photoshop", "illustrator", "canva"],
    "3D Modeling": ["3d modeling", "blender", "3ds max", "cinema 4d", "3d rendering"],
    "Video Editing": ["video editing", "premiere pro", "after effects"],
    "Copywriting": ["copywriting", "content writing", "blog writing", "ghostwriting"],
    "Email Marketing": ["email marketing", "klaviyo", "mailchimp"],
    "Lead Generation": ["lead generation", "cold calling", "appointment setting"],
    "Virtual Assistant": ["virtual assistant", "admin support", "data entry"],
    "Mobile App Development": ["mobile app", "ios app", "android app", "swift", "kotlin"],
    "Blockchain": ["blockchain", "solidity", "smart contract", "web3", "nft"],
}

DOMAIN: dict[str, str] = {}
for _s in ["Python", "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "scikit-learn", "NLP", "LLM", "RAG",
           "LangChain", "Prompt Engineering", "Fine-tuning", "Computer Vision", "OpenCV", "YOLO", "Hugging Face",
           "Vector Database", "MLOps", "MLflow", "Time Series Forecasting", "Recommendation Systems", "Chatbot",
           "Speech Recognition", "AWS SageMaker"]:
    DOMAIN[_s] = "ai_ml"
for _s in ["JavaScript", "TypeScript", "React", "Next.js", "Vue.js", "Angular", "Node.js", "Express", "Django",
           "Django REST Framework", "Flask", "FastAPI", "REST API", "GraphQL", "PostgreSQL", "MySQL", "MongoDB", "Redis",
           "Celery", "Docker", "Kubernetes", "AWS", "GCP", "Azure", "CI/CD", "Tailwind CSS", "HTML/CSS", "Stripe",
           "WebSockets", "Authentication", "Firebase", "Shopify", "React Native", "Flutter", "PHP", "Java", "Go"]:
    DOMAIN[_s] = "web"
for _s in ["SQL", "R", "pandas", "NumPy", "Excel", "Google Sheets", "Power BI", "DAX", "Tableau", "Looker Studio",
           "dbt", "Snowflake", "BigQuery", "Airflow", "ETL", "Data Visualization", "Statistics", "A/B Testing",
           "Data Cleaning", "Google Analytics", "Data Analysis", "KPI Reporting"]:
    DOMAIN[_s] = "data"

# Upwork "Category_*" tag -> canonical (tags not listed fall back to alias matching)
UPWORK_TAG_MAP = {
    "web development": "HTML/CSS", "front-end development": "React", "back-end development": "REST API",
    "full-stack development": "React", "api": "REST API", "web application": "React", "web design": "HTML/CSS",
    "artificial intelligence": "Machine Learning", "data science": "Machine Learning", "data mining": "Data Analysis",
    "data analytics": "Data Analysis", "microsoft excel": "Excel", "microsoft power bi": "Power BI",
    "data visualization": "Data Visualization", "database": "SQL", "database design": "PostgreSQL",
    "amazon web services": "AWS", "chatgpt": "LLM", "openai api": "LLM", "generative ai": "LLM",
    "natural language processing": "NLP", "computer vision": "Computer Vision", "deep learning": "Deep Learning",
    "machine learning model": "Machine Learning", "python script": "Python", "automation": "Python",
    "business intelligence": "KPI Reporting", "statistical analysis": "Statistics", "etl pipeline": "ETL",
    "mobile app development": "Mobile App Development", "android app development": "Mobile App Development",
    "ios development": "Mobile App Development", "social media marketing": "Social Media Marketing",
    "3d modeling": "3D Modeling", "3d rendering": "3D Modeling", "email marketing": "Email Marketing",
    "search engine optimization": "SEO", "graphic design": "Graphic Design", "video editing": "Video Editing",
    "content writing": "Copywriting", "lead generation": "Lead Generation", "marketing strategy": "Social Media Marketing",
    "digital marketing": "Social Media Marketing", "facebook advertising": "Social Media Marketing",
    "wordpress": "PHP", "shopify": "Shopify", "laravel": "PHP", "javascript": "JavaScript", "react": "React",
    "node.js": "Node.js", "django": "Django", "flask": "Flask", "python": "Python", "sql": "SQL", "tableau": "Tableau",
    "looker studio": "Looker Studio", "google sheets": "Google Sheets", "pandas": "pandas", "scikit-learn": "scikit-learn",
    "tensorflow": "TensorFlow", "pytorch": "PyTorch", "next.js": "Next.js", "typescript": "TypeScript",
    "mongodb": "MongoDB", "postgresql": "PostgreSQL", "mysql": "MySQL", "docker": "Docker", "firebase": "Firebase",
    "blockchain": "Blockchain", "smart contract": "Blockchain", "web scraping": "Web Scraping",
    "data entry": "Virtual Assistant", "virtual assistance": "Virtual Assistant",
}


_AMBIGUOUS = {"r", "go"}  # never matched as bare aliases


IMPLIES = {"Django REST Framework": "Django", "Next.js": "React", "Express": "Node.js", "DAX": "Power BI"}


@lru_cache(maxsize=1)
def _alias_index() -> list[tuple[str, re.Pattern[str], str]]:
    """(alias, boundary regex, canonical) for every alias; substring test runs first (fast path)."""
    out = []
    for canon, aliases in SKILLS.items():
        for a in {canon.lower(), *aliases}:
            if a not in _AMBIGUOUS:
                out.append((a, re.compile(rf"(?<![a-z0-9]){re.escape(a)}(?![a-z0-9])"), canon))
    return out


def extract_skills(text: str) -> list[str]:
    """Deterministic canonical-skill extraction from free text (ordered by first mention)."""
    low = text.lower()
    found: dict[str, int] = {}
    for alias, pat, canon in _alias_index():
        if alias in low:
            m = pat.search(low)
            if m and (canon not in found or m.start() < found[canon]):
                found[canon] = m.start()
    for child, parent in IMPLIES.items():
        if child in found and parent not in found:
            found[parent] = found[child] + 1
    # " R " as a language only when written with typical context
    if re.search(r"\b(?:in|using|with) R\b|\bR\s*(?:/|and)\s*(?:Python|SQL)|\bRStudio\b", text):
        found.setdefault("R", text.find(" R"))
    return [k for k, _ in sorted(found.items(), key=lambda kv: kv[1])]


def map_upwork_tag(tag: str) -> str | None:
    t = tag.strip().lower()
    if not t:
        return None
    if t in UPWORK_TAG_MAP:
        return UPWORK_TAG_MAP[t]
    hits = extract_skills(tag)
    return hits[0] if hits else None


def skill_domain(skill: str) -> str:
    return DOMAIN.get(skill, "other")
