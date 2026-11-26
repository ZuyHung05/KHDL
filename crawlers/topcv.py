from __future__ import annotations

from .site import build_board, parse_args, resume_rows, run

TOPCV_BADGE_PREFIXES = ("GẤP", "PRO", "PROS", "HOT", "TOP", "PHẢN HỒI VƯỢT TRỘI")


def _clean(s: str) -> str:
    s = s.replace("\n", " ").strip()
    words = s.split()
    while words and words[0].upper() in TOPCV_BADGE_PREFIXES:
        words = words[1:]
    return " ".join(words).strip()


def _clean_row(row: dict) -> dict:
    row = dict(row)
    for key in ("title", "company"):
        if row.get(key):
            row[key] = _clean(row[key])
    return row


def extract_rows(page) -> list[dict]:
    return page.eval_on_selector_all(
        "div.job-item-search-result",
        """els=>els.map(
        card=>{
          const titleA=card.querySelector('a[href*="/viec-lam/"]');
          const h3=card.querySelector('h3');
          const t=(sel)=>{const el=card.querySelector(sel); return el? el.innerText.trim():'';};
          const rawTitle=h3? h3.innerText.trim():'';
          const company=t('[class*="company"]');
          return {
            job_url: titleA? titleA.href.split('?')[0] : '',
            url: titleA? titleA.href : '',
            title: rawTitle,
            company: company,
            location: t('[class*="address"]')||t('[class*="location"]'),
            salary: t('[class*="salary"]'),
            site: "topcv",
          };
        })""",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args("topcv", "TopCV job listing crawler", {})
    board = build_board("topcv", extract_rows, clean=_clean_row)
    hosts = [] if args.no_dns_pin else [board.host]
    resume_ = resume_rows(args.out) if args.resume else None
    run(board, out=args.out, pages=args.pages, headless=args.headless, hosts=hosts, existing=resume_)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
