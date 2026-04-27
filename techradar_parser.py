import io
import json
import re
import sys
from pathlib import Path

import pandas as pd
import requests
from bs4 import BeautifulSoup, Tag

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def safe_filename(name: str) -> str:
    name = clean_text(name)
    name = re.sub(r'[<>:"/\\|?*]+', "", name)
    name = re.sub(r"\s+", "_", name)
    return name[:180] if name else "phone"


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def get_main_content(soup: BeautifulSoup) -> Tag:
    main_content = soup.find("section", class_="content-wrapper")
    if main_content is None:
        raise ValueError("Could not find TechRadar main content")
    return main_content


def extract_phone_name(main_article: Tag, fallback_title: str) -> str:
    section_h2 = main_article.find_all("h2", class_="article-body__section")
    if len(section_h2) >= 2:
        span = section_h2[1].find("span")
        if span:
            phone_name_text = clean_text(span.get_text(" ", strip=True))
            if "review" in phone_name_text.lower():
                phone_name_text = re.split(r"\breview\b", phone_name_text, flags=re.IGNORECASE)[0]
            if ":" in phone_name_text:
                phone_name_text = phone_name_text.split(":", 1)[0]
            phone_name_text = phone_name_text.strip()
            if phone_name_text:
                return phone_name_text

    fallback = re.split(r"\breview\b", fallback_title, flags=re.IGNORECASE)[0]
    return clean_text(fallback)


def parse_table(table_tag: Tag | None) -> tuple[dict, list[dict]]:
    if table_tag is None:
        return {}, []

    dataframe = pd.read_html(io.StringIO(str(table_tag)))[0]
    spec_table = pd.DataFrame()
    rating_table = pd.DataFrame()

    if len(dataframe.columns) == 2:
        spec_table = dataframe
        next_table = table_tag.find_next("table")
        if next_table is not None:
            rating_table = pd.read_html(io.StringIO(str(next_table)))[0]
    elif len(dataframe.columns) == 3:
        rating_table = dataframe

    spec_data: dict = {}
    if not spec_table.empty:
        spec_data = spec_table.set_index(spec_table.columns[0])[spec_table.columns[1]].to_dict()
        spec_data = {clean_text(str(key)): clean_text(str(value)) for key, value in spec_data.items()}

    rating_data: list[dict] = []
    if not rating_table.empty:
        rating_data = []
        for record in rating_table.to_dict(orient="records"):
            normalized = {clean_text(str(key)): clean_text(str(value)) for key, value in record.items()}
            rating_data.append(normalized)

    return spec_data, rating_data


def parse_article(url: str) -> dict:
    soup = get_soup(url)
    main_content = get_main_content(soup)
    main_article = main_content.find("div", id="article-body")
    if main_article is None:
        raise ValueError("Could not find TechRadar article body")

    title_tag = soup.find("h1")
    fallback_title = clean_text(title_tag.get_text(" ", strip=True)) if title_tag else ""
    phone_name = extract_phone_name(main_article, fallback_title)

    pretty_verdict = main_content.find("div", class_="pretty-verdict")
    verdict_text = ""
    verdict_pros = []
    verdict_cons = []

    if pretty_verdict is not None:
        verdict_node = pretty_verdict.find("div", class_="pretty-verdict__verdict")
        if verdict_node and verdict_node.find("p"):
            verdict_text = clean_text(verdict_node.find("p").get_text(" ", strip=True))

        pros_node = pretty_verdict.find("div", class_="pretty-verdict__pros")
        if pros_node:
            verdict_pros = [
                clean_text(p.get_text(" ", strip=True))
                for p in pros_node.find_all("p")
                if clean_text(p.get_text(" ", strip=True))
            ]

        cons_node = pretty_verdict.find("div", class_="pretty-verdict__cons")
        if cons_node:
            verdict_cons = [
                clean_text(p.get_text(" ", strip=True))
                for p in cons_node.find_all("p")
                if clean_text(p.get_text(" ", strip=True))
            ]

    paragraphs = [
        clean_text(p.get_text(" ", strip=True)) + "\n\n"
        for p in main_article.find_all("p", recursive=False)
        if clean_text(p.get_text(" ", strip=True))
    ]
    bullet_points = [
        clean_text(item.get_text(" ", strip=True))
        for item in main_article.find_all("li")
        if clean_text(item.get_text(" ", strip=True))
    ]

    spec_data, rating_data = parse_table(main_article.find("table"))

    return {
        "source": "techradar",
        "phone_name": phone_name,
        "article_url": url,
        "verdict": {
            "text": verdict_text,
            "pros": verdict_pros,
            "cons": verdict_cons,
        },
        "article_content": {
            "paragraphs": paragraphs,
            "bullet_points": bullet_points,
        },
        "tables": {
            "specifications": spec_data,
            "ratings": rating_data,
        },
    }


def save_json(data: dict, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_path = output_dir / f"{safe_filename(data['phone_name'])}.json"
    with open(file_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=4)
    return file_path


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: python techradar_parser.py "ARTICLE_URL" [OUTPUT_DIR]')
        sys.exit(1)

    article_url = sys.argv[1]
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("parsed_phone") / "techradar"
    data = parse_article(article_url)
    path = save_json(data, output_dir)
    print(f"Saved: {path.resolve()}")


if __name__ == "__main__":
    main()
