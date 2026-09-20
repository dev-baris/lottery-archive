"""Generate a static index.html showing the latest lottery draw results."""

import csv
from datetime import UTC, date, datetime
from html import escape
from pathlib import Path
from shutil import copyfile

from archive_policy import LOTTO_FIRST_DATE

REPO_ROOT = Path(__file__).parent.parent

LOTTERIES = [
    {
        "id": "at",
        "name": "Lotto 6 aus 45",
        "flag": "🇦🇹",
        "csv": REPO_ROOT / "at" / "lotto_6aus45" / "results.csv",
        "archive_url": "at/lotto_6aus45/results.csv",
        "archive_start": LOTTO_FIRST_DATE,
        "numbers": ["n1", "n2", "n3", "n4", "n5", "n6"],
        "bonus": [("Zusatzzahl", "zusatzzahl")],
        "bonus_style": "bonus-red",
    },
    {
        "id": "de",
        "name": "Lotto 6 aus 49",
        "flag": "🇩🇪",
        "csv": REPO_ROOT / "de" / "lotto_6aus49" / "results.csv",
        "archive_url": "de/lotto_6aus49/results.csv",
        "archive_start": LOTTO_FIRST_DATE,
        "numbers": ["n1", "n2", "n3", "n4", "n5", "n6"],
        "bonus": [("Superzahl", "superzahl")],
        "bonus_style": "bonus-red",
    },
    {
        "id": "eu",
        "name": "Euromillionen",
        "flag": "🇪🇺",
        "csv": REPO_ROOT / "eu" / "euromillions" / "results.csv",
        "archive_url": "eu/euromillions/results.csv",
        "numbers": ["n1", "n2", "n3", "n4", "n5"],
        "bonus": [("Lucky Star", "s1"), ("Lucky Star", "s2")],
        "bonus_style": "bonus-eu",
    },
    {
        "id": "eurojackpot",
        "name": "Eurojackpot",
        "flag": "🇪🇺",
        "csv": REPO_ROOT / "eu" / "eurojackpot" / "results.csv",
        "archive_url": "eu/eurojackpot/results.csv",
        "numbers": ["n1", "n2", "n3", "n4", "n5"],
        "bonus": [("Eurozahl", "e1"), ("Eurozahl", "e2")],
        "bonus_style": "bonus-eu",
    },
]


def read_last_row(csv_path: Path, *, minimum_date: date | None = None) -> dict[str, str] | None:
    """Read the latest dated record, independently of input row order.

    Reject malformed data instead of publishing a partial or misleading card.
    Full game-specific checks live in ``check_integrity.py``.
    """
    latest = None
    latest_date = None
    with csv_path.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle, strict=True)
        if not reader.fieldnames or "date" not in reader.fieldnames:
            raise ValueError(f"{csv_path}: missing date column")
        if len(reader.fieldnames) != len(set(reader.fieldnames)):
            raise ValueError(f"{csv_path}: duplicate CSV columns")
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise ValueError(f"{csv_path}: malformed CSV row {reader.line_num}")
            try:
                draw_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                if draw_date.isoformat() != row["date"]:
                    raise ValueError("date must use YYYY-MM-DD")
            except ValueError as exc:
                raise ValueError(f"{csv_path}: invalid date at row {reader.line_num}") from exc
            if minimum_date is not None and draw_date < minimum_date:
                raise ValueError(
                    f"{csv_path}: row {reader.line_num} date {draw_date} "
                    f"precedes archive start ({minimum_date})"
                )
            if latest_date is None or draw_date > latest_date:
                latest, latest_date = row, draw_date
    return latest


def format_date(iso_date: str) -> str:
    d = datetime.strptime(iso_date, "%Y-%m-%d").date()
    return d.strftime("%d.%m.%Y")


def render_lottery_card(lottery: dict, row: dict) -> str:
    main_balls = "".join(
        f'<span class="ball main">{escape(str(row[col]))}</span>'
        for col in lottery["numbers"]
    )

    bonus_balls = ""
    for label, col in lottery["bonus"]:
        value = row.get(col)
        val = str(value).strip() if value is not None else ""
        if val:
            bonus_balls += (
                f'<span class="ball {escape(lottery["bonus_style"])}" '
                f'title="{escape(label)}" aria-label="{escape(label)} {escape(val)}">'
                f'{escape(val)}</span>'
            )

    draw_date = format_date(row["date"])
    archive_link = ""
    if lottery.get("archive_url"):
        start = lottery.get("archive_start")
        download_label = (
            f"Ziehungen ab {start.year} als CSV" if start else "Alle Ziehungen als CSV"
        )
        archive_link = (
            f'<p class="archive-link"><a href="{escape(lottery["archive_url"])}" '
            f'download>{escape(download_label)}</a></p>'
        )

    return f"""
    <article class="card" id="{escape(lottery['id'])}">
      <header>
        <span class="flag" aria-hidden="true">{escape(lottery['flag'])}</span>
        <h2>{escape(lottery['name'])}</h2>
      </header>
      <p class="draw-date">Ziehung vom <time datetime="{escape(row['date'])}">{draw_date}</time></p>
      <div class="balls">
        {main_balls}
        {"<span class='separator'>+</span>" + bonus_balls if bonus_balls else ""}
      </div>
      {archive_link}
    </article>"""


def generate_html(cards: list[str], generated_at: str) -> str:
    cards_html = "\n".join(cards)
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Lottery Archive – Letzte Ziehungen</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    body {{
      font-family: system-ui, -apple-system, sans-serif;
      background: #0f172a;
      color: #e2e8f0;
      min-height: 100vh;
      padding: 2rem 1rem;
    }}

    header.page-header {{
      text-align: center;
      margin-bottom: 2.5rem;
    }}

    header.page-header h1 {{
      font-size: 2rem;
      font-weight: 700;
      letter-spacing: -0.02em;
      color: #f8fafc;
    }}

    header.page-header p {{
      margin-top: 0.5rem;
      color: #94a3b8;
      font-size: 0.9rem;
    }}

    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
      gap: 1.5rem;
      max-width: 1100px;
      margin: 0 auto;
    }}

    .card {{
      background: #1e293b;
      border: 1px solid #334155;
      border-radius: 1rem;
      padding: 1.5rem;
    }}

    .card header {{
      display: flex;
      align-items: center;
      gap: 0.6rem;
      margin-bottom: 0.75rem;
    }}

    .flag {{ font-size: 1.6rem; line-height: 1; }}

    .card h2 {{
      font-size: 1.1rem;
      font-weight: 600;
      color: #f1f5f9;
    }}

    .draw-date {{
      font-size: 0.82rem;
      color: #94a3b8;
      margin-bottom: 1.1rem;
    }}

    .balls {{
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
    }}

    .ball {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 2.6rem;
      height: 2.6rem;
      border-radius: 50%;
      font-size: 0.95rem;
      font-weight: 700;
    }}

    .ball.main {{
      background: #2563eb;
      color: #fff;
    }}

    .ball.bonus-red {{
      background: #dc2626;
      color: #fff;
    }}

    .ball.bonus-eu {{
      background: #f59e0b;
      color: #1e293b;
    }}

    .separator {{
      color: #94a3b8;
      font-weight: 700;
      font-size: 1.2rem;
    }}

    footer {{
      text-align: center;
      margin-top: 3rem;
      color: #94a3b8;
      font-size: 0.8rem;
    }}

    a {{
      color: #60a5fa;
      text-underline-offset: 0.15em;
    }}

    .archive-link {{ margin-top: 1.25rem; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <header class="page-header">
    <h1>Lottery Archive</h1>
    <p>Letzte archivierte Ziehungsergebnisse</p>
  </header>

  <main class="grid">
    {cards_html}
  </main>

  <footer>
    <p>Aktualisiert: {escape(generated_at)}</p>
  </footer>
</body>
</html>
"""


def main(out_dir: Path | None = None) -> Path:
    """Build a self-contained Pages artifact, including every linked CSV."""
    cards = []
    for lottery in LOTTERIES:
        row = read_last_row(lottery["csv"], minimum_date=lottery.get("archive_start"))
        if row is None:
            raise ValueError(f"No data found in {lottery['csv']}")
        cards.append(render_lottery_card(lottery, row))

    generated_at = datetime.now(UTC).strftime("%d.%m.%Y %H:%M UTC")
    html = generate_html(cards, generated_at)

    out_dir = out_dir or REPO_ROOT / "public"
    out_dir.mkdir(exist_ok=True, parents=True)
    for lottery in LOTTERIES:
        destination = out_dir / lottery["archive_url"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        copyfile(lottery["csv"], destination)
    output = out_dir / "index.html"
    output.write_text(html, encoding="utf-8")
    print(f"Generated: {output}")
    return output


if __name__ == "__main__":
    main()
