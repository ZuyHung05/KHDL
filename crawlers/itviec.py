from __future__ import annotations

from .site import build_board, parse_args, run


def extract_rows(page) -> list[dict]:
    return page.eval_on_selector(
        "div.card-jobs-list",
        r"""root=>{
          const out=[];
          root.querySelectorAll('h3 a[href*="/it-jobs/"]').forEach(a=>{
            let card=a;
            while(card && !card.matches('.job-card') && card.parentElement && card.parentElement!==root) card=card.parentElement;
            if(!card||card===root) card=a;
            const parts=(card.innerText||'').split('\n').map(s=>s.trim()).filter(Boolean);
            const title=(a.innerText||'').trim();
            let company='';
            const ti=parts.indexOf(title);
            if(ti>=0){ const nxt=parts[ti+1]; if(nxt && !/salary|in to|posted/i.test(nxt)) company=nxt; }
            const cityRe=/Ho Chi Minh|Hà Nội|Ha Noi|Đà Nẵng|Da Nang|Hải Phòng|Hai Phong|Cần Thơ|Can Tho|Binh Duong|Biên Hòa|Bien Hoa|Remote/i;
            let location='';
            for(const p of parts){ if(cityRe.test(p) && p.length<40){ location=p; break; } }
            out.push({
              job_url: a.href.split('?')[0],
              url: a.href,
              title,
              company,
              location,
              site: "itviec",
            });
          });
          return out;
        }""",
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args("itviec", "ITviec job listing crawler", {})
    board = build_board("itviec", extract_rows)
    hosts = [] if args.no_dns_pin else [board.host]
    run(board, out=args.out, pages=args.pages, headless=args.headless, hosts=hosts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
