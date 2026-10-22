# Phone Reviews + LLM

A Python project that collects smartphone reviews from **Notebookcheck** and **TechRadar**, combines information about the same models, and answers questions using a local LLM.

## How it works

1. **Collect reviews:** Scrapy crawls review listings, while BeautifulSoup extracts phone names, specifications, ratings, verdicts, pros, cons, and article text into JSON files.
2. **Match phones:** SentenceTransformers converts phone names into embeddings. Records from the two sources are matched using cosine similarity (at least `0.7`) and an additional check of numeric model identifiers.
3. **Build the knowledge base:** Matched reviews are combined into a single document and stored in ChromaDB. A similarity heatmap helps inspect the matching results.
4. **Answer questions:** Relevant documents are retrieved from ChromaDB and passed as context to `llama3`, running locally through Ollama. The model generates an answer based on the collected reviews (RAG).

## Technologies

- **Python**, **Scrapy**, **BeautifulSoup**, **lxml** - crawling and HTML parsing.
- **SentenceTransformers** (`paraphrase-multilingual-MiniLM-L12-v2`) - text embeddings.
- **NumPy**, **scikit-learn** - similarity calculations and matching.
- **ChromaDB** - persistent vector storage and retrieval.
- **Ollama**, **llama3**, **OpenAI Python SDK** - local answer generation through an OpenAI-compatible API.
- **pandas**, **Matplotlib**, **Seaborn** - similarity heatmap visualization.

## Project structure

- `scrapy_*.py`, `*_parser.py` - source-specific crawlers and parsers.
- `dataset/` - collected reviews and processed JSON data.
- `vectors_database/chromedb.py` - phone matching and vector database creation.
- `vectors_database/retrieval.py` - retrieval and LLM question answering.

The main challenges were finding suitable review sources, extracting phone names and useful content from different HTML layouts, filtering noise, and matching records across both websites.
