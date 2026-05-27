import scrapy
import scrapy.crawler as crawler

from bs4 import BeautifulSoup, Tag
import techradar_parser

from pathlib import Path
from urllib.parse import urlencode, urljoin

import notebookcheck_parser

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


def is_probable_phone_review(url: str) -> bool:
    lower = url.lower()
    if not ("review" in lower or "test" in lower):
        return False
    if any(hint in lower for hint in NON_PHONE_HINTS):
        return False
    return any(hint in lower for hint in PHONE_HINTS)


class NotebookcheckSpider(scrapy.Spider):

    # manifest.append(
    #             {
    #                 "source": source_name,
    #                 "article_url": link,
    #                 "phone_name": data.get("phone_name", ""),
    #                 "canonical_name": data.get("canonical_name", ""),
    #                 "file": str(file_path),
    #             }
    #         )

    name = "my_noteboookcheck_spider"

    custom_settings = {
        "DOWNLOAD_DELAY": "2.0",
        "ROBOTSTXT_OBEY": True,
        "AUTOTHROTTLE_ENABLED": True,
        "USER_AGENT": f"{name}",
    }

    start_urls = [
        "https://www.notebookcheck.net/Reviews.55.0.html?&items_per_page=100&hide_youtube=1&hide_external_reviews=1&showHighlightedTags=1&tagArray[]=10&typeArray[]=1&id=55"
    ]

    for i in range(1, 3):
        start_urls.append(
            f"https://www.notebookcheck.net/Reviews.55.0.html?&items_per_page=100&hide_youtube=1&hide_external_reviews=1&showHighlightedTags=1&ns_page={i}&tagArray[]=10&typeArray[]=1&id=55"
        )

    def __init__(self, output_path="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_path = output_path

    def parse(self, response):
        soup = BeautifulSoup(response.body, "lxml")
        main_content = soup.find("div", class_="introa_whole")
        links = [link.get("href") for link in main_content.find_all("a")]
        links = [link for link in links if is_probable_phone_review(link)]

        for link in links:
            yield scrapy.Request(
                link, self.parse_item, cb_kwargs={"original_url": link}
            )

    def parse_item(self, response, original_url):
        notebookcheck_parser.main(response, original_url, self.output_path)


def main(out=""):
    process = crawler.CrawlerProcess()
    process.crawl(NotebookcheckSpider, output_path=out)
    process.start()


if __name__ == "__main__":
    main()
