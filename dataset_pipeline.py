import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode, urljoin


import scrapy
import scrapy.crawler as crawler

from scrapy_notebookcheck import NotebookcheckSpider
from scrapy_techradar import TechRadarSpider

BASE_DIR = Path("dataset")
RAW_DIR = BASE_DIR / "raw"
MERGED_DIR = BASE_DIR / "merged"
JSONL_PATH = BASE_DIR / "training_examples.jsonl"


NOISY_NAME_PARTS = {
    "smartphone",
    "smartphones",
    "phone",
    "phones",
    "review",
    "test",
    "preview",
}


def canonical_phone_name(name: str) -> str:
    text = name.lower()
    text = text.replace("+", " plus ")
    text = re.sub(r"\b5g\b", " 5g ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    parts = [part for part in text.split() if part and part not in NOISY_NAME_PARTS]
    return "_".join(parts)


def flatten_text(data: dict) -> str:
    chunks = []

    verdict = data.get("verdict", {})
    if verdict.get("text"):
        chunks.append(verdict["text"])
    chunks.extend(verdict.get("pros", []))
    chunks.extend(verdict.get("cons", []))

    article_content = data.get("article_content", {})
    chunks.extend(article_content.get("paragraphs", []))
    chunks.extend(article_content.get("bullet_points", []))

    cleaned = []
    seen = set()
    for chunk in chunks:
        text = re.sub(r"\s+", " ", str(chunk)).strip()
        if text and text not in seen:
            seen.add(text)
            cleaned.append(text)

    return "\n".join(cleaned)


def load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, payload: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=4)


def crawl_source(source: str, output_dir: Path) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    process = crawler.CrawlerProcess()
    if source in {"techradar", "all"}:
        process.crawl(TechRadarSpider, output_path=output_dir / "techradar")
    if source in {"notebookcheck", "all"}:
        process.crawl(NotebookcheckSpider, output_path=output_dir / "notebookcheck")
    process.start()


def merge_datasets(raw_root: Path, merged_root: Path) -> list[dict]:
    grouped: dict[str, dict] = {}

    for source_dir in raw_root.iterdir():
        if not source_dir.is_dir():
            continue

        for json_path in source_dir.glob("*.json"):
            if json_path.name == "_manifest.json":
                continue

            record = load_json(json_path)
            key = record.get("canonical_name") or canonical_phone_name(
                record.get("phone_name", "")
            )
            if not key:
                continue

            phone_entry = grouped.setdefault(
                key,
                {
                    "phone_key": key,
                    "phone_name_candidates": [],
                    "sources": {},
                    "combined": {
                        "pros": [],
                        "cons": [],
                        "specifications": {},
                        "ratings": {},
                        "texts": [],
                    },
                },
            )

            phone_name = record.get("phone_name", "")
            if phone_name and phone_name not in phone_entry["phone_name_candidates"]:
                phone_entry["phone_name_candidates"].append(phone_name)

            source_name = record.get("source", source_dir.name)
            source_bucket = phone_entry["sources"].setdefault(source_name, [])
            source_bucket.append(record)

            for item in record.get("verdict", {}).get("pros", []):
                if item not in phone_entry["combined"]["pros"]:
                    phone_entry["combined"]["pros"].append(item)

            for item in record.get("verdict", {}).get("cons", []):
                if item not in phone_entry["combined"]["cons"]:
                    phone_entry["combined"]["cons"].append(item)

            specs = record.get("tables", {}).get("specifications", {})
            if specs:
                phone_entry["combined"]["specifications"][source_name] = specs

            ratings = record.get("tables", {}).get("ratings", [])
            if ratings:
                phone_entry["combined"]["ratings"][source_name] = ratings

            flattened = flatten_text(record)
            if flattened:
                phone_entry["combined"]["texts"].append(
                    {
                        "source": source_name,
                        "article_url": record.get("article_url", ""),
                        "text": flattened,
                    }
                )

    merged_items = []
    for key, phone_entry in grouped.items():
        merged_payload = {
            "phone_key": key,
            "primary_name": (
                phone_entry["phone_name_candidates"][0]
                if phone_entry["phone_name_candidates"]
                else key
            ),
            "aliases": phone_entry["phone_name_candidates"],
            "sources": phone_entry["sources"],
            "combined": phone_entry["combined"],
        }
        save_json(merged_root / f"{key}.json", merged_payload)
        merged_items.append(merged_payload)

    return merged_items


def export_training_jsonl(items: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        for item in items:
            combined = item.get("combined", {})
            training_row = {
                "phone_key": item["phone_key"],
                "primary_name": item["primary_name"],
                "aliases": item.get("aliases", []),
                "pros": combined.get("pros", []),
                "cons": combined.get("cons", []),
                "specifications": combined.get("specifications", {}),
                "ratings": combined.get("ratings", {}),
                "documents": combined.get("texts", []),
            }
            handle.write(json.dumps(training_row, ensure_ascii=False) + "\n")


def run(source: str) -> None:
    source = source.lower()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MERGED_DIR.mkdir(parents=True, exist_ok=True)
    crawl_source(
        source,
        RAW_DIR,
    )

    merged_items = merge_datasets(RAW_DIR, MERGED_DIR)
    export_training_jsonl(merged_items, JSONL_PATH)
    print(f"Merged phones: {len(merged_items)}")
    print(f"Training file: {JSONL_PATH.resolve()}")


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "all"
    if source not in {"all", "techradar", "notebookcheck"}:
        print("Usage: python dataset_pipeline.py [all|techradar|notebookcheck]")
        sys.exit(1)
    run(source)


if __name__ == "__main__":
    main()
