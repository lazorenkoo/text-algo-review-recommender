import pandas as pd
from bs4 import BeautifulSoup
import requests
import io
import json

# Link do strony którą chcemy zesrapowac
url = "https://www.techradar.com/phones/google-pixel-phones/google-pixel-9a-review"

page = requests.get(url)

soup = BeautifulSoup(page.content)

# Znajdź główną zawartość

main_content = soup.find("section", class_="content-wrapper")

# Pobierz preety verdict

preety_verdict = main_content.find("div", class_="pretty-verdict")

preety_verdict_text = (
    preety_verdict.find("div", class_="pretty-verdict__verdict").find("p").text
)

preety_verdict_pros = preety_verdict.find(
    "div", class_="pretty-verdict__pros"
).find_all("p")

preety_verdict_cons = preety_verdict.find(
    "div", class_="pretty-verdict__cons"
).find_all("p")

# Zamień wady i zalety z preety verdict do listy

preety_verdict_pros_list = [p.text for p in preety_verdict_pros]
preety_verdict_cons_list = [p.text for p in preety_verdict_cons]

# Znajdz pozostałą część strony
main_article = main_content.find("div", id="article-body")

# Cały tekst z tej strony zawarty jest w paragrafach
p_text = main_article.find_all("p", recursive=False)

# Wszystkie listy wyliczane, później zamieniane są na bullet points
strong_text = main_article.find_all("li")

main_article_list = [f"{p.text}\n\n" for p in p_text]
strong_text_list = [t.text for t in strong_text]

# Znajdz tabelke ze specyfikacja. Zawssze jest to pierwsza tabela
spec_table_html = main_article.find("table")

df = pd.read_html(io.StringIO(str(spec_table_html)))[0]

spec_table = pd.DataFrame()
rating_table = pd.DataFrame()

# Moze okazać się że nie ma tabeli ze specyfikacja, wtedy następną powinna byc podsumowująca która ma 3 kolumny
# Jesli nie znajdziemy żadnej tabeli oba DataFrame pozostaną puste
if len(df.columns) == 2:

    next_table = str(spec_table_html.find_next("table"))
    spec_table = df
    rating_table = pd.read_html(io.StringIO(next_table))[0]
elif len(df.columns) == 3:
    rating_table = df
    spec_table = pd.DataFrame()

# Zamiana tabel na słowniki
spec_data = spec_table.to_dict(orient="records")
rating_data = rating_table.to_dict(orient="records")

# Zmiana mapowania zamiast index=>column[0], index=>column[1]
# Zamieniamy na column[0]=>column[1]
if not spec_table.empty:
    spec_data = spec_table.set_index(spec_table.columns[0])[
        spec_table.columns[1]
    ].to_dict()

# Znalezienie span w ktorym jest ukryta nazwa telefonu
# Zawsze znajduje się w drugim h2 o klasie "article-body__section"
phone_name_text = (
    main_article.find("h2", class_="article-body__section")
    .find_next_sibling("h2", class_="article-body__section")
    .find("span")
    .text
)
# Tekst nie jest jednoznaczny
# Czasami przed ":" występuje "review"
# Znalazłem tylko 2 rózne przypadki
# Powinno być uniwersalne, ale trzeba na to zwrócić uwagę, bo może zdażyć się sytuacja gdzie nazwa telefonu zostanie blędnie pobrana
if "review" in phone_name_text:
    phone_name = phone_name_text.split("review")[0]
elif ":" in phone_name_text:
    phone_name = phone_name_text.split(":")[0]

phone_name = phone_name.strip()


final_json_data = {
    "phone_name": phone_name,
    "article_url": url,
    "verdict": {
        "text": preety_verdict_text,
        "pros": preety_verdict_pros_list,
        "cons": preety_verdict_cons_list,
    },
    "article_content": {
        "paragraphs": main_article_list,
        "bullet_points": strong_text_list,
    },
    "tables": {"specifications": spec_data, "ratings": rating_data},
}


with open(f"Reviews/{phone_name}.json", "w", encoding="utf-8") as f:
    json.dump(final_json_data, f, ensure_ascii=False, indent=4)
