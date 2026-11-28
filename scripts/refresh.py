"""Append complete matched-tenor observations without replacing the chart UI."""
import calendar
import json
import math
import re
from bisect import bisect_right
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from xml.etree import ElementTree

TENORS = (1, 3, 6, 12)
EUR_URL = ("https://reports.suomenpankki.fi/WebForms/ReportViewerPage.aspx?"
           "output=xml&report=%2Ftilastot%2Fmarkkina-_ja_hallinnolliset_korot%2Feuribor_korot_xml_short_en")


def fetch(url):
    with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0 (ARX ATF benchmark update)"}), timeout=60) as response:
        return response.read()


class TableRows(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.row = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self.row = []
        elif tag == "td":
            self.cell = []

    def handle_data(self, text):
        if self.cell is not None:
            self.cell.append(text)

    def handle_endtag(self, tag):
        if tag == "td" and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        elif tag == "tr" and self.row:
            self.rows.append(self.row)


def load_sources(since):
    usd_json = json.loads(fetch("https://markets.newyorkfed.org/api/rates/secured/sofrai/search.json?startDate=" + since))
    usd = {date.fromisoformat(r["effectiveDate"]): float(r["index"]) for r in usd_json["refRates"]}
    swiss = json.loads(fetch("https://data.snb.ch/api/cube/zirepo/data/json/en?fromDate=" + since))
    history = next(s["values"] for s in swiss["timeseries"] if s["metadata"]["key"].endswith("{H0}"))
    chf = {date.fromisoformat(r["date"]): float(r["value"]) for r in history if r["value"] is not None}
    table = TableRows()
    table.feed(fetch("https://www.bluegamma.io/compounded-rates/saron").decode())
    closes = {}
    for cells in table.rows:
        if len(cells) == 6 and re.fullmatch(r"\d{1,2} [A-Z][a-z]{2} \d{4}", cells[0]):
            day = datetime.strptime(cells[0], "%d %b %Y").date()
            closes[day] = float("".join(cells[1].split()).rstrip("%"))
    if not closes or not set(chf).intersection(closes):
        raise ValueError("Recent SARON closes do not overlap the official history")
    for day, rate in closes.items():
        chf.setdefault(day, rate)
    eur = {}
    for period in ElementTree.fromstring(fetch(EUR_URL)).findall(".//{*}period"):
        entries = {r.get("name"): r.find("{*}intr").get("value") for r in period.findall(".//{*}rate")}
        values = [entries.get(f"{t} month (act/360)") for t in TENORS]
        if all(values):
            eur[date.fromisoformat(period.get("value"))] = list(map(float, values))
    return usd, chf, eur


def new_rows(usd, chf, eur, last):
    chf_index = {}
    level = 1
    previous = None
    for day, rate in sorted(chf.items()):
        if previous:
            days = (day - previous).days
            if days > 7:
                raise ValueError(f"Gap in SARON before {day}")
            level *= 1 + chf[previous] * days / 36000
        chf_index[day] = level
        previous = day
    joint = sorted(usd.keys() & chf.keys())
    for day in sorted(set(joint) & eur.keys()):
        if day <= last or (day.month, day.day) in {(1, 1), (5, 1), (12, 25), (12, 26)}:
            continue
        row = [day.isoformat()]
        for tenor, euro in zip(TENORS, eur[day]):
            year, month = divmod(day.year * 12 + day.month - 1 - tenor, 12)
            target = date(year, month + 1, min(day.day, calendar.monthrange(year, month + 1)[1]))
            start = joint[bisect_right(joint, target) - 1]
            if not 0 <= (target - start).days <= 6:
                raise ValueError(f"Missing start date for {day} {tenor}M")
            days = (day - start).days
            scale = 36000 / days
            rates = [(usd[day] / usd[start] - 1) * scale, euro, (chf_index[day] / chf_index[start] - 1) * scale]
            if not all(math.isfinite(v) and abs(v) < 100 for v in rates):
                raise ValueError(f"Invalid rates on {day}")
            row.extend([*(round(v * 1e6) for v in rates), days])
        yield row


def main():
    page = Path(__file__).resolve().parents[1] / "index.html"
    html = page.read_text()
    match = re.search(r"const observations=(\[.*?\]);", html)
    rows = json.loads(match[1])
    last = date.fromisoformat(rows[-1][0])
    usd, chf, eur = load_sources((last - timedelta(days=380)).isoformat())
    print("Latest dates:", max(usd), max(chf), max(eur))
    additions = list(new_rows(usd, chf, eur, last))
    if additions:
        encoded = json.dumps(additions, separators=(",", ":"))
        page.write_text(html[:match.end(1)-1] + "," + encoded[1:] + html[match.end(1):])
    print(f"Added {len(additions)} observations. Latest: {(rows + additions)[-1][0]}")


if __name__ == "__main__":
    main()
