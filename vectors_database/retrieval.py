import os
import chromadb
from chromadb.utils import embedding_functions
from openai import OpenAI

openai_client = OpenAI(
    base_url="http://localhost:11434/v1",
    api_key="ollama",
)
PATH = "./chroma_db"
COLLECTION_NAME = "linked_phones_bot"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
client = chromadb.PersistentClient(path=PATH)

sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=MODEL_NAME
)

collection = client.get_or_create_collection(
    name=COLLECTION_NAME, embedding_function=sentence_transformer_ef
)


def query_rag(user_query, llm_client, n_results=3, metadata_filter=None):
    """
    Wyszukuje kontekst w ChromaDB (opcjonalnie z filtrem metadanych)
    i generuje odpowiedź przy użyciu LLM.
    """
    # 1. Przeszukanie bazy wektorowej
    results = collection.query(
        query_texts=[user_query],
        n_results=n_results,
        where=metadata_filter,
    )

    # Sprawdzenie, czy baza cokolwiek zwróciła
    if not results or not results["documents"] or not results["documents"][0]:
        return "Niestety, nie znalazłem w bazie żadnych informacji na ten temat."

    retrieved_docs = results["documents"][0]
    metadatas = results["metadatas"][0]

    # 2. Budowanie kontekstu dla LLM
    context = "\n\n".join(retrieved_docs)
    # 3. Przygotowanie promptów
    system_prompt = (
        "Jesteś ekspertem ds. smartfonów. Odpowiadaj na pytania użytkownika w języku polskim, "
        "wyłącznie w oparciu o dostarczony kontekst. Jeśli w kontekście nie ma bezpośredniej "
        "odpowiedzi na pytanie, powiedz grzecznie, że nie dysponujesz takimi informacjami w bazie."
    )

    user_prompt = f"KONTEKST:\n{context}\n\nPYTANIE: {user_query}"

    # 4. Wywołanie LLM
    try:
        response = llm_client.chat.completions.create(
            model="llama3",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Błąd podczas generowania odpowiedzi przez LLM: {e}"


my_filter = {"is_linked": "true"}
question = "Poleć niedrogi telefon z dobrym aparatem"

# Wywołanie pełnego RAG-a
response = query_rag(
    user_query=question,
    llm_client=openai_client,
    n_results=10,
    metadata_filter=my_filter,
)

print("\n=== ODPOWIEDŹ SYSTEMU RAG ===")
print(response)
