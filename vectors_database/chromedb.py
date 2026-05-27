import chromadb
from chromadb.utils import embedding_functions
import json
from pathlib import Path
import re
import numpy as np
from sklearn.metrics.pairwise import cosine_similarity
import seaborn as sns
import matplotlib.pyplot as plt
import pandas as pd

DB_PATH = "./chroma_db"
COLLECTION_NAME = "linked_phones_bot"
MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"

client = chromadb.PersistentClient(path=DB_PATH)
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=MODEL_NAME
)


client.delete_collection(COLLECTION_NAME)


collection = client.get_or_create_collection(
    name=COLLECTION_NAME, embedding_function=sentence_transformer_ef
)


def get_nums(text):

    return set(re.findall(r"\d+[a-z]?", text))


def load_data(folder_path):
    """Wczytuje pliki JSON z folderu"""
    data_list = []
    path = Path(folder_path)
    if not path.exists():
        print(f"Folder {folder_path} doesnt exist")
        return []
    for file in path.glob("*.json"):
        with open(file, "r", encoding="utf-8") as f:
            js = json.load(f)
            data_list.append(
                {
                    "name": js.get("phone_name", "Unknown"),
                    "content": js,
                    "path": str(file),
                }
            )
    return data_list


nc_data = load_data("../dataset/raw/notebookcheck")
tr_data = load_data("../dataset/raw/techradar")

if not nc_data or not tr_data:
    print("No data")
    exit()

print(f"Loaded {len(nc_data)} from Notebookcheck and {len(tr_data)} from TechRadar.")

# Generate vectors for techradar and notebookcheck
nc_names = [item["name"] for item in nc_data]
tr_names = [item["name"] for item in tr_data]

nc_embeddings = sentence_transformer_ef(nc_names)
tr_embeddings = sentence_transformer_ef(tr_names)

similarity_matrix = cosine_similarity(nc_embeddings, tr_embeddings)


def create_rich_document(nc_item, tr_item=None):

    text = nc_item["content"]

    # If there is techradar review, attach it
    if tr_item:
        text["techradar"] = tr_item["content"]

    return json.dumps(text)


def create_database():
    final_entries = []
    used_tr_indices = set()
    matched_count = 0

    for idx_nc, nc_item in enumerate(nc_data):
        best_match = None
        max_sim = -1
        best_tr_idx = -1

        # Notebookcheck vector

        nc_similarities = similarity_matrix[idx_nc]
        potential_matches = np.argsort(nc_similarities)[::-1]
        for idx_tr in potential_matches:
            sim = nc_similarities[idx_tr]

            if sim < 0.7:
                break

            if idx_tr in used_tr_indices:
                continue

            tr_item = tr_data[idx_tr]
            if get_nums(nc_item["name"]) == get_nums(tr_item["name"]):
                max_sim = sim
                best_tr_idx = idx_tr
                break

        # Budowanie dokumentu i metadanych
        if best_tr_idx != -1:
            best_match = tr_data[best_tr_idx]
            matched_count += 1
            used_tr_indices.add(best_tr_idx)

            combined_text = create_rich_document(nc_item, best_match)
            metadata = {
                "full_name": nc_item["name"],
                "nc_path": nc_item["path"],
                "tr_path": best_match["path"],
                "is_linked": "true",
                "similarity_score": float(max_sim),
            }
        else:
            combined_text = create_rich_document(nc_item)
            metadata = {
                "full_name": nc_item["name"],
                "nc_path": nc_item["path"],
                "tr_path": "none",
                "is_linked": "false",
                "similarity_score": 0.0,
            }

        final_entries.append(
            {
                "doc": combined_text,
                "meta": metadata,
                "id": f"merged_{nc_item['name'].replace(' ', '_')}",
            }
        )

    print(f"- Unique models: {len(final_entries)}")
    print(f"- Sucessfully merged (NC + TR): {matched_count}")
    print(f"- Only notebookcheck: {len(final_entries) - matched_count}")

    # Save to ChromeDB
    collection.add(
        documents=[e["doc"] for e in final_entries],
        metadatas=[e["meta"] for e in final_entries],
        ids=[e["id"] for e in final_entries],
    )


def generate_heatmap(nc_data, tr_data, similarity_matrix, n=50):

    # Pobieramy nazwy i ograniczamy je do n
    nc_names = [item["name"] for item in nc_data[:n]]
    tr_names = [item["name"] for item in tr_data[:n]]

    df_heatmap = pd.DataFrame(
        similarity_matrix[:n, :n], index=nc_names, columns=tr_names
    )

    plt.figure(figsize=(40, 30))
    sns.heatmap(
        df_heatmap,
        annot=True,
        fmt=".2f",
        cmap="YlGnBu",
        xticklabels=True,
        yticklabels=True,
        cbar_kws={"label": "Podobieństwo Kosinusowe"},
    )

    plt.title(
        f"Macierz Podobieństwa (Top {n} modeli): Notebookcheck vs TechRadar",
        fontsize=16,
    )
    plt.xticks(rotation=45, ha="right")  # Pochylenie napisów na dole
    plt.tight_layout()  # Dopasowanie marginesów
    plt.show()


create_database()
# generate_heatmap(nc_data, tr_data, similarity_matrix, 30)
