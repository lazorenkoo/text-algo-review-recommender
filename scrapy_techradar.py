import scrapy
import scrapy.crawler as crawler

from bs4 import BeautifulSoup, Tag
import techradar_parser
from twisted.internet import threads


def is_techradar_phone_review(url: str) -> bool:
    return (
        url.startswith("https://www.techradar.com/phones/")
        and "phone-accessories" not in url
    )


class TechRadarSpider(scrapy.Spider):

    name = "my_techradar_spider"

    custom_settings = {
        "DOWNLOAD_DELAY": "0.2",
        "ROBOTSTXT_OBEY": True,
        "AUTOTHROTTLE_ENABLED": True,
        "USER_AGENT": f"{name}",
    }

    # start_urls = ["https://www.techradar.com/archive/2026/04"]
    # start_urls = [
    #     f"https://www.techradar.com/archive/2026/{i}" for i in range(4, 0, -1)
    # ]
    start_urls = [
        f"https://www.techradar.com/phones/reviews/page/{i}" for i in range(1, 10)
    ]
    # for year in range(2025, 2024, -1):
    #     for month in range(12, 0, -1):
    #         start_urls.append(f"https://www.techradar.com/archive/{year}/{month}")

    def __init__(self, output_path="", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.output_path = output_path

    def parse(self, response):
        links = response.css("div.listingResults.review a::attr(href)").getall()
        links = [link for link in links if is_techradar_phone_review(link)]
        for link in links:
            yield scrapy.Request(
                link, self.parse_item, cb_kwargs={"original_url": link}
            )

    def parse_item(self, response, original_url):
        if response.css("h1.review-title-long").get():
            threads.deferToThread(
                techradar_parser.main, response, original_url, self.output_path
            )


def main(out=""):
    process = crawler.CrawlerProcess()
    process.crawl(TechRadarSpider, output_path=out)
    process.start()


if __name__ == "__main__":
    main()
