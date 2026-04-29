import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlencode, urljoin

import requests

import notebookcheck_parser
import techradar_parser

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

BASE_DIR = Path("dataset")
RAW_DIR = BASE_DIR / "raw"
MERGED_DIR = BASE_DIR / "merged"
JSONL_PATH = BASE_DIR / "training_examples.jsonl"
LIGHT_JSON_PATH = BASE_DIR / "training_examples.json"

TECHRADAR_LIST_URL = "https://www.techradar.com/phones/reviews"
NOTEBOOKCHECK_LIST_URL = "https://www.notebookcheck.net/Reviews.55.0.html"
DEFAULT_WORKERS = max(4, min(16, (os.cpu_count() or 4) * 2))
NOTEBOOKCHECK_QUERY = {
    "items_per_page": 100,
    "hide_youtube": 1,
    "hide_external_reviews": 1,
    "showHighlightedTags": 1,
    "tagArray[]": 10,
    "typeArray[]": 1,
    "id": 55,
}

PHONE_HINTS = [
    "phone",
    "smartphone",
    "iphone",
    "galaxy",
    "pixel",
    "redmi",
    "xiaomi",
    "motorola",
    "oneplus",
    "honor",
    "oppo",
    "vivo",
    "realme",
    "sony",
    "huawei",
    "nokia",
    "poco",
    "doogee",
    "oukitel",
    "nubia",
    "tecno",
    "nothing",
    "razr",
    "xperia",
]

NON_PHONE_HINTS = [
    "charger",
    "power-bank",
    "power-bank-review",
    "controller",
    "case-review",
    "case-for-",
    "earbuds",
    "headphones",
    "storage-expansion",
    "thermal-camera",
    "gimbal",
    "stabilizer",
    "cable",
    "charging-station",
    "pad",
    "battery-pack",
]

NOISY_NAME_PARTS = {
    "smartphone",
    "smartphones",
    "phone",
    "phones",
    "review",
    "test",
    "preview",
}


def fetch_html(url: str) -> str:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return response.text


def normalize_url(base_url: str, href: str) -> str:
    href = href.strip()
    if not href:
        return ""
    return urljoin(base_url, href)


def extract_links(html: str, base_url: str) -> list[str]:
    links = []
    seen = set()
    for href in re.findall(r'href="([^"]+)"', html, flags=re.IGNORECASE):
        full = normalize_url(base_url, href)
        if full and full not in seen:
            seen.add(full)
            links.append(full)
    return links


def is_techradar_phone_review(url: str) -> bool:
    lower = url.lower()
    if not (lower.startswith("https://www.techradar.com/phones/") and "-review" in lower):
        return False
    if any(hint in lower for hint in NON_PHONE_HINTS):
        return False
    return any(hint in lower for hint in PHONE_HINTS)


def is_probable_phone_review(url: str) -> bool:
    lower = url.lower()
    if not ("review" in lower or "test" in lower):
        return False
    if any(hint in lower for hint in NON_PHONE_HINTS):
        return False
    return any(hint in lower for hint in PHONE_HINTS)


def discover_techradar_links(max_pages: int = 25) -> list[str]:
    found = []
    seen = set()
    empty_pages = 0

    for page_number in range(1, max_pages + 1):
        if page_number == 1:
            url = TECHRADAR_LIST_URL
        else:
            url = f"{TECHRADAR_LIST_URL}/page/{page_number}"

        try:
            html = fetch_html(url)
        except requests.RequestException:
            break

        page_links = [
            link
            for link in extract_links(html, url)
            if is_techradar_phone_review(link)
        ]

        new_links = [link for link in page_links if link not in seen]
        if not new_links:
            empty_pages += 1
            if empty_pages >= 2:
                break
            continue

        empty_pages = 0
        for link in new_links:
            seen.add(link)
            found.append(link)

    return found


def notebookcheck_page_url(page_number: int) -> str:
    query = dict(NOTEBOOKCHECK_QUERY)
    if page_number > 1:
        query["ns_page"] = page_number
    return f"{NOTEBOOKCHECK_LIST_URL}?{urlencode(query, doseq=True)}"


def discover_notebookcheck_links(max_pages: int = 40) -> list[str]:
    found = []
    seen = set()
    empty_pages = 0

    for page_number in range(1, max_pages + 1):
        url = notebookcheck_page_url(page_number)
        try:
            html = fetch_html(url)
        except requests.RequestException:
            break

        page_links = [
            link
            for link in extract_links(html, NOTEBOOKCHECK_LIST_URL)
            if link.startswith("https://www.notebookcheck.net/") and is_probable_phone_review(link)
        ]

        new_links = [link for link in page_links if link not in seen]
        if not new_links:
            empty_pages += 1
            if empty_pages >= 2:
                break
            continue

        empty_pages = 0
        for link in new_links:
            seen.add(link)
            found.append(link)

    return found


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


def parse_and_save_article(source_name: str, index: int, total: int, link: str, parse_func, output_dir: Path) -> dict:
    data = parse_func(link)
    data["source"] = source_name
    data["canonical_name"] = canonical_phone_name(data.get("phone_name", ""))
    file_path = output_dir / f"{source_name}_{index:04d}_{data['canonical_name'] or 'unknown'}.json"
    save_json(file_path, data)
    print(f"[{source_name}] saved {index}/{total}: {data.get('phone_name', link)}")
    return {
        "source": source_name,
        "article_url": link,
        "phone_name": data.get("phone_name", ""),
        "canonical_name": data.get("canonical_name", ""),
        "file": str(file_path),
    }


def crawl_source(source_name: str, links: list[str], parse_func, output_dir: Path, max_workers: int = DEFAULT_WORKERS) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    indexed_links = list(enumerate(links, start=1))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                parse_and_save_article,
                source_name,
                index,
                len(links),
                link,
                parse_func,
                output_dir,
            ): (index, link)
            for index, link in indexed_links
        }

        for future in as_completed(future_map):
            index, link = future_map[future]
            try:
                manifest.append(future.result())
            except Exception as exc:
                manifest.append(
                    {
                        "source": source_name,
                        "article_url": link,
                        "error": str(exc),
                    }
                )
                print(f"[{source_name}] failed {index}/{len(links)}: {link} -> {exc}")

    manifest.sort(key=lambda item: item.get("file", item.get("article_url", "")))
    save_json(output_dir / "_manifest.json", manifest)
    return manifest


def merge_datasets(raw_root: Path, merged_root: Path) -> list[dict]:
    grouped: dict[str, dict] = {}

    for source_dir in raw_root.iterdir():
        if not source_dir.is_dir():
            continue

        for json_path in source_dir.glob("*.json"):
            if json_path.name == "_manifest.json":
                continue

            record = load_json(json_path)
            key = record.get("canonical_name") or canonical_phone_name(record.get("phone_name", ""))
            if not key:
                continue

            phone_entry = grouped.setdefault(
                key,
                {
                    "phone_key": key,
                    "phone_name_candidates": [],
                    "documents": [],
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
                document_entry = {
                    "source": source_name,
                    "article_url": record.get("article_url", ""),
                    "phone_name": phone_name,
                    "text": flattened,
                }
                phone_entry["documents"].append(document_entry)
                phone_entry["combined"]["texts"].append(document_entry)

    merged_items = []
    for key, phone_entry in grouped.items():
        merged_payload = {
            "phone_key": key,
            "primary_name": phone_entry["phone_name_candidates"][0] if phone_entry["phone_name_candidates"] else key,
            "aliases": phone_entry["phone_name_candidates"],
            "documents": phone_entry["documents"],
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
                "documents": item.get("documents", []),
            }
            handle.write(json.dumps(training_row, ensure_ascii=False) + "\n")


def export_training_json(items: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    lightweight_items = []
    for item in items:
        combined = item.get("combined", {})
        lightweight_items.append(
            {
                "phone_key": item["phone_key"],
                "primary_name": item["primary_name"],
                "aliases": item.get("aliases", []),
                "pros": combined.get("pros", []),
                "cons": combined.get("cons", []),
                "specifications": combined.get("specifications", {}),
                "ratings": combined.get("ratings", {}),
                "documents": item.get("documents", []),
            }
        )
    save_json(output_path, lightweight_items)


def run(source: str, limit: int | None = None) -> None:
    source = source.lower()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    MERGED_DIR.mkdir(parents=True, exist_ok=True)

    jobs = []
    if source in {"techradar", "all"}:
        jobs.append(("techradar", discover_techradar_links, techradar_parser.parse_article, RAW_DIR / "techradar"))
    if source in {"notebookcheck", "all"}:
        jobs.append(
            (
                "notebookcheck",
                discover_notebookcheck_links,
                notebookcheck_parser.parse_article,
                RAW_DIR / "notebookcheck",
            )
        )

    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as executor:
        futures = {}
        for source_name, discover_func, parse_func, output_dir in jobs:
            futures[
                executor.submit(
                    lambda s=source_name, d=discover_func, p=parse_func, o=output_dir, l=limit: crawl_source(
                        s, d()[:l] if l is not None else d(), p, o
                    )
                )
            ] = source_name

        for future in as_completed(futures):
            source_name = futures[future]
            try:
                future.result()
            except Exception as exc:
                print(f"[{source_name}] source job failed: {exc}")

    merged_items = merge_datasets(RAW_DIR, MERGED_DIR)
    export_training_jsonl(merged_items, JSONL_PATH)
    export_training_json(merged_items, LIGHT_JSON_PATH)
    print(f"Merged phones: {len(merged_items)}")
    print(f"Training file: {JSONL_PATH.resolve()}")


def main() -> None:
    source = sys.argv[1] if len(sys.argv) > 1 else "all"
    if source not in {"all", "techradar", "notebookcheck"}:
        print('Usage: python dataset_pipeline.py [all|techradar|notebookcheck] [LIMIT]')
        sys.exit(1)

    limit = None
    if len(sys.argv) > 2:
        try:
            limit = int(sys.argv[2])
        except ValueError:
            print("LIMIT must be an integer")
            sys.exit(1)
        if limit <= 0:
            print("LIMIT must be greater than 0")
            sys.exit(1)

    run(source, limit)


if __name__ == "__main__":
    main()
