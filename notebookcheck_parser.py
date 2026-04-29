import json
import re
import sys
from collections import OrderedDict
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

KNOWN_SPEC_KEYS = {
    "Processor",
    "Graphics adapter",
    "Memory",
    "Display",
    "Storage",
    "Connections",
    "Networking",
    "Size",
    "Battery",
    "Charging",
    "Operating System",
    "Camera",
    "Additional features",
    "Released",
    "Weight",
    "Price",
    "Links",
}

ALLOWED_RATING_KEYS = [
    "Chassis",
    "Keyboard",
    "Pointing Device",
    "Connectivity",
    "Weight",
    "Battery",
    "Display",
    "Games Performance",
    "Application Performance",
    "AI Performance",
    "Temperature",
    "Noise",
    "Audio",
    "Camera",
    "CO2 Emissions",
    "Materials",
    "Packaging",
    "Power Use",
    "Repairability",
    "Software Updates",
    "Total Sustainability Score",
]

PHONE_BRANDS_PATTERN = (
    r"\b(?:iphone|galaxy|pixel|xiaomi|motorola|oneplus|honor|oppo|vivo|realme|sony|huawei|poco|nubia|tecno|nothing|xperia)\b"
)


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def paragraph_text(text: str) -> str:
    text = clean_text(text)
    return text + "\n\n" if text else ""


def safe_filename(name: str) -> str:
    name = clean_text(name)
    name = re.sub(r'[<>:"/\\|?*]+', "", name)
    name = re.sub(r"\s+", "_", name)
    return name[:180] if name else "phone"


def get_soup(url: str) -> BeautifulSoup:
    response = requests.get(url, headers=HEADERS, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def get_main_root(soup: BeautifulSoup) -> Tag:
    return soup.find("main") or soup.find("article") or soup.body


def find_h1(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    return ""


def find_h2_containing(root: Tag, keyword: str) -> Tag | None:
    keyword = keyword.lower()
    for h2 in root.find_all("h2"):
        text = clean_text(h2.get_text(" ", strip=True)).lower()
        if keyword in text:
            return h2
    return None


def find_h3_after_h2(h2_tag: Tag, keyword: str) -> Tag | None:
    keyword = keyword.lower()
    for el in h2_tag.find_all_next():
        if isinstance(el, Tag):
            if el.name == "h2":
                break
            if el.name == "h3":
                text = clean_text(el.get_text(" ", strip=True)).lower()
                if keyword in text:
                    return el
    return None


def collect_text_nodes_until_heading(start_tag: Tag, stop_headings: set[str]) -> list[str]:
    lines = []
    seen = set()

    for el in start_tag.next_elements:
        if el is start_tag:
            continue

        if isinstance(el, Tag) and el.name in stop_headings:
            break

        if isinstance(el, NavigableString):
            parent = el.parent
            if parent and parent.name in {"script", "style", "noscript"}:
                continue

            text = clean_text(str(el))
            if not text or text in seen:
                continue

            seen.add(text)
            lines.append(text)

    return lines


def collect_text_nodes_between(start_tag: Tag, end_tag: Tag | None) -> list[str]:
    lines = []
    seen = set()

    for el in start_tag.next_elements:
        if el is start_tag:
            continue

        if end_tag is not None and el is end_tag:
            break

        if isinstance(el, NavigableString):
            parent = el.parent
            if parent and parent.name in {"script", "style", "noscript"}:
                continue

            text = clean_text(str(el))
            if not text or text in seen:
                continue

            seen.add(text)
            lines.append(text)

    return lines


def cleanup_phone_candidate(text: str) -> str:
    text = clean_text(text)
    text = re.sub(r"^[>\-:\s]+", "", text)
    text = re.sub(r"\b(?:review|test|preview)\b.*$", "", text, flags=re.IGNORECASE)

    if ":" in text:
        right = text.split(":", 1)[1].strip()
        if re.search(PHONE_BRANDS_PATTERN, right, flags=re.IGNORECASE):
            text = right

    brand_match = re.search(PHONE_BRANDS_PATTERN, text, flags=re.IGNORECASE)
    if brand_match and brand_match.start() > 0:
        prefix = text[: brand_match.start()].strip()
        if len(prefix.split()) >= 3:
            text = text[brand_match.start() :].strip()

    text = re.sub(r"\bsmartphone\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" :-,")
    return clean_text(text)


def slug_to_phone_name(article_url: str) -> str:
    path_parts = [part for part in urlparse(article_url).path.split("/") if part]
    if not path_parts:
        return ""

    slug = path_parts[-1]
    slug = re.sub(r"\.\d+\.\d+\.html$", "", slug, flags=re.IGNORECASE)
    slug = re.sub(r"-(?:review|test|preview).*$", "", slug, flags=re.IGNORECASE)
    slug = slug.replace("-", " ")
    return cleanup_phone_candidate(slug)


def get_phone_name(soup: BeautifulSoup, title: str, article_url: str) -> str:
    root = get_main_root(soup)

    for key in ["Verdict on the", "Specifications of the"]:
        h2 = find_h2_containing(root, key)
        if h2:
            text = clean_text(h2.get_text(" ", strip=True))
            match = re.search(rf"{re.escape(key)}\s+(.+)", text, re.IGNORECASE)
            if match:
                candidate = cleanup_phone_candidate(match.group(1))
                if candidate:
                    return candidate

    match = re.search(r"-\s*([A-Z][A-Za-z0-9+ .()-]+?)\s+(?:review|test|preview)\b", title)
    if match:
        candidate = cleanup_phone_candidate(match.group(1))
        if candidate:
            return candidate

    slug_candidate = slug_to_phone_name(article_url)
    if slug_candidate:
        return slug_candidate

    fallback = re.split(r"\b(?:review|Review|test|Test|preview|Preview)\b", title, maxsplit=1)[0]
    return cleanup_phone_candidate(fallback)


def is_noise_line(text: str) -> bool:
    low = text.lower()

    bad_starts = (
        "download your licensed",
        "test device courtesy",
        "reviews",
        "news",
        "back to the verdict",
        "possible alternatives in comparison",
        "please share our article",
        "read all",
        "comment on this article",
        "source on google",
        "editor of the",
        "translator",
        "contact & imprint",
        "data privacy declaration",
        "cookie settings",
        "loading comments",
        "add as a preferred",
    )

    if low.startswith(bad_starts):
        return True

    return text in {"+", "-", "Pros", "Cons", "4"}


def parse_verdict(root: Tag) -> dict:
    verdict_h2 = find_h2_containing(root, "Verdict")
    if not verdict_h2:
        return {"text": "", "pros": [], "cons": []}

    pros_h3 = find_h3_after_h2(verdict_h2, "Pros")
    cons_h3 = find_h3_after_h2(verdict_h2, "Cons")

    verdict_lines = collect_text_nodes_between(verdict_h2, pros_h3)
    verdict_parts = []

    for line in verdict_lines:
        if is_noise_line(line) or len(line) < 40:
            continue
        verdict_parts.append(line)

    pros = []
    if pros_h3:
        for line in collect_text_nodes_until_heading(pros_h3, {"h2", "h3"}):
            line = line.lstrip("+").strip()
            if is_noise_line(line):
                continue
            if 2 <= len(line) <= 120:
                pros.append(line)

    cons = []
    if cons_h3:
        for line in collect_text_nodes_until_heading(cons_h3, {"h2", "h3"}):
            line = line.lstrip("-").strip()
            if is_noise_line(line):
                continue
            if 2 <= len(line) <= 120:
                cons.append(line)

    return {
        "text": clean_text(" ".join(verdict_parts)),
        "pros": list(OrderedDict.fromkeys(pros)),
        "cons": list(OrderedDict.fromkeys(cons)),
    }


def parse_specifications(root: Tag) -> OrderedDict:
    spec_h2 = find_h2_containing(root, "Specifications")
    if not spec_h2:
        return OrderedDict()

    lines = collect_text_nodes_until_heading(spec_h2, {"h2"})
    filtered = []

    for line in lines:
        low = line.lower()
        if is_noise_line(line):
            continue
        if low.startswith("see all specifications"):
            continue
        if low.startswith("[+] add to comparison"):
            continue
        if "compare devices" in low:
            continue
        if low.startswith("note: the manufacturer"):
            continue
        filtered.append(line)

    specs = OrderedDict()
    current_key = None

    for line in filtered:
        key = line.rstrip(":")
        if key in KNOWN_SPEC_KEYS:
            current_key = key
            if current_key != "Links" and (current_key + ":") not in specs:
                specs[current_key + ":"] = ""
            continue

        if current_key is not None and current_key != "Links":
            full_key = current_key + ":"
            specs[full_key] = (specs[full_key] + " " + line).strip()

    cleaned_specs = OrderedDict()
    for key, value in specs.items():
        value = clean_text(value)
        if value:
            cleaned_specs[key] = value

    return cleaned_specs


def looks_like_real_paragraph(text: str) -> bool:
    if is_noise_line(text) or len(text) < 70 or len(text.split()) < 10:
        return False

    digit_count = sum(ch.isdigit() for ch in text)
    alpha_count = sum(ch.isalpha() for ch in text)
    if alpha_count == 0 or digit_count > alpha_count:
        return False

    bad_fragments = [
        "fps",
        "mbit/s",
        "ms rise",
        "ms fall",
        "tooltip",
        "min:",
        "max:",
        "average of class",
        "distribution of brightness",
        "screen flickering / pwm",
        "display response times",
        "colorchecker",
        "gps test:",
        "image comparison",
        "click to load images",
        "response time black to white",
        "response time 50% grey",
        "power consumption:",
        "battery runtime:",
        "reader / idle",
        "wifi websurfing",
        "big buck bunny",
        "load (maximum brightness)",
    ]

    low = text.lower()
    return not any(fragment in low for fragment in bad_fragments)


def parse_intro_and_body_paragraphs(root: Tag) -> list[str]:
    paragraphs = []
    seen = set()

    toc_h2 = find_h2_containing(root, "Table of Contents")
    spec_h2 = find_h2_containing(root, "Specifications")
    rating_h2 = find_h2_containing(root, "Notebookcheck overall rating") or find_h2_containing(
        root, "Notebookcheck total rating"
    )

    if toc_h2 and spec_h2:
        for line in collect_text_nodes_between(toc_h2, spec_h2):
            if looks_like_real_paragraph(line) and line not in seen:
                seen.add(line)
                paragraphs.append(paragraph_text(line))

    for h2 in root.find_all("h2"):
        if spec_h2 is None:
            break

        if h2 is spec_h2:
            continue

        title = clean_text(h2.get_text(" ", strip=True)).lower()
        if rating_h2 is not None and h2 is rating_h2:
            break
        if "verdict" in title or "price and availability" in title or "table of contents" in title:
            continue
        if "specifications" in title:
            continue
        if "possible alternatives in comparison" in title or "transparency" in title:
            break
        if spec_h2.sourceline and h2.sourceline and h2.sourceline < spec_h2.sourceline:
            continue

        for line in collect_text_nodes_until_heading(h2, {"h2"}):
            if looks_like_real_paragraph(line) and line not in seen:
                seen.add(line)
                paragraphs.append(paragraph_text(line))

    return paragraphs


def parse_ratings(root: Tag) -> list[dict]:
    rating_h2 = find_h2_containing(root, "Notebookcheck overall rating") or find_h2_containing(
        root, "Notebookcheck total rating"
    )
    if not rating_h2:
        return []

    lines = collect_text_nodes_until_heading(rating_h2, {"h2"})
    ratings = []

    for key in ALLOWED_RATING_KEYS:
        found = None
        for i, line in enumerate(lines):
            if key.lower() not in line.lower():
                continue

            same_line = re.search(r"(\d+(?:\.\d+)?)%", line)
            if same_line:
                found = same_line.group(1) + "%"
                break

            for candidate in lines[i + 1 : i + 4]:
                match = re.search(r"(\d+(?:\.\d+)?)%", candidate)
                if match:
                    found = match.group(1) + "%"
                    break

            if found:
                break

        if found:
            ratings.append({"Attributes": key, "Notes": "", "Rating": found})

    return ratings


def parse_article(article_url: str) -> dict:
    soup = get_soup(article_url)
    root = get_main_root(soup)

    title = find_h1(soup)
    phone_name = get_phone_name(soup, title, article_url)

    return {
        "source": "notebookcheck",
        "phone_name": phone_name,
        "article_url": article_url,
        "verdict": parse_verdict(root),
        "article_content": {
            "paragraphs": parse_intro_and_body_paragraphs(root),
            "bullet_points": [],
        },
        "tables": {
            "specifications": parse_specifications(root),
            "ratings": parse_ratings(root),
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
        print('Usage: python notebookcheck_parser.py "ARTICLE_URL" [OUTPUT_DIR]')
        sys.exit(1)

    article_url = sys.argv[1]
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("parsed_phone") / "notebookcheck"
    data = parse_article(article_url)
    path = save_json(data, output_dir)
    print(f"Saved: {path.resolve()}")


if __name__ == "__main__":
    main()
