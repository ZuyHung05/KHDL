"""Count eligible groups by stored evidence-based family and role."""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq


PATTERNS = {
    'Software Engineering': {
        'Fullstack': r'full.?stack|full stack',
        'Backend': r'back.?end|server.side|\bbackend\b',
        'Frontend': r'front.?end|reactjs|vuejs|angular',
        'Mobile': r'\bmobile\b|android|\bios\b|flutter|react native',
        'Embedded': r'embedded|nhúng|firmware',
        'UI/UX': r'ui.?ux|ux.?ui|product designer|ux designer|ui designer',
        'Software khác': r'software|developer|lập trình|\bdev\b|web|ứng dụng|application engineer|programmer',
    },
    'Data & AI': {
        'Data Engineer': r'data engineer|data engineering|kỹ sư dữ liệu|dwh developer|data warehouse engineer',
        'Data Scientist': r'data scientist|data science|khoa học dữ liệu',
        'AI/ML Engineer': r'ai engineer|ml engineer|machine learning|deep learning|artificial intelligence|ai/ml|ai developer|agentic ai',
        'Data Analyst/BI': r'data analyst|phân tích dữ liệu|business intelligence|\bbi analyst\b|\bbi developer\b',
    },
    'Infrastructure & Security': {
        'DevOps/SRE': r'devops|devsecops|site reliability|\bsre\b',
        'Cloud': r'cloud engineer|cloud architect|cloud solution architect|cloud operations? engineer|cloud platform engineer(?:ing lead)?|cloudops|cloud specialist',
        'Cybersecurity': r'cyber|security|bảo mật|an toàn thông tin|pentest|soc analyst',
        'System/Network/IT Support': r'it support|helpdesk|network engineer|system engineer|system admin|server operation|quản trị hệ thống|kỹ thuật it|infrastructure',
    },
    'QA & Business': {
        'QA/Testing': r'\bqa\b|\bqc\b|quality assurance|tester|testing|kiểm thử|kiem thu',
        'Business Analyst': r'business analyst|phân tích nghiệp vụ|\bbrse\b|bridge system engineer',
        'ERP/SAP': r'\bsap\b|\berp\b|oracle ebs|dynamics 365',
    },
}

PRIORITY = ['Fullstack','Data Engineer','Data Scientist','AI/ML Engineer','Data Analyst/BI',
            'DevOps/SRE','Cloud','Cybersecurity','QA/Testing','Business Analyst','ERP/SAP',
            'UI/UX','Embedded','Mobile','Backend','Frontend','System/Network/IT Support','Software khác']
COMPILED = [(family, role, re.compile(expr, re.I)) for family, roles in PATTERNS.items() for role, expr in roles.items()]


def role_for(title: str) -> tuple[str, str]:
    matches = [(family, role) for family, role, expr in COMPILED if expr.search(title or '')]
    if not matches:
        return 'Khác/chưa rõ nghề', 'Khác/chưa rõ'
    # Broad software words must not override a more specific role.
    family, role = min(matches, key=lambda pair: PRIORITY.index(pair[1]))
    return family, role


def run(input_path: Path, output_dir: Path) -> dict:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    schema = pq.read_schema(input_path)
    stored_roles = {'role_family', 'primary_role'}.issubset(schema.names)
    columns = ['record_id', 'source_id', 'title', 'eligibility_status'] + (['role_family', 'primary_role', 'role_confidence', 'skill_count', 'skills_evidence'] if stored_roles else [])
    rows = pq.read_table(input_path, columns=columns).to_pylist()
    eligible = [r for r in rows if r['eligibility_status'] == 'eligible']
    tagged = []
    for r in eligible:
        family, role = (r['role_family'], r['primary_role']) if stored_roles else role_for(r['title'])
        if family == 'unknown': family = 'Khác/chưa rõ nghề'
        if role == 'unknown': role = 'Chưa rõ nghề trong nhóm' if family != 'Khác/chưa rõ nghề' else 'Khác/chưa rõ'
        tagged.append({**r, 'role_family':family, 'primary_role':role})
    group_counts = Counter(r['role_family'] for r in tagged)
    role_counts = Counter((r['role_family'], r['primary_role']) for r in tagged)
    assert sum(group_counts.values()) == len(eligible) == sum(role_counts.values())
    output_dir.mkdir(parents=True, exist_ok=True)
    with (output_dir / 'jd_roles.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['record_id', 'source_id', 'title', 'role_family', 'primary_role'] + (['role_confidence','skill_count'] if stored_roles else []))
        writer.writeheader(); writer.writerows({k:r[k] for k in writer.fieldnames} for r in tagged)
    for name, fields, items in (
        ('nhom_nghe.csv', ['role_family', 'jd_count'], [{'role_family':k,'jd_count':v} for k,v in group_counts.items()]),
        ('nghe_chi_tiet.csv', ['role_family', 'primary_role', 'jd_count'], [{'role_family':f,'primary_role':r,'jd_count':v} for (f,r),v in role_counts.items()]),
    ):
        with (output_dir / name).open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(sorted(items, key=lambda x:(x['role_family'],x.get('primary_role',''))))

    groups = list(PATTERNS) + ['Khác/chưa rõ nghề']
    values = [group_counts[g] for g in groups]
    fig, ax = plt.subplots(figsize=(11, 5.8))
    bars = ax.barh(groups[::-1], values[::-1], color=['#74859b','#a788bf','#5c87a9','#d6a950','#159f80'][::-1])
    ax.bar_label(bars, padding=4); ax.set_xlim(0, max(values)*1.15)
    ax.set_xlabel('Số nhóm JD phù hợp'); ax.set_title(f'JD phù hợp theo nhóm nghề chính (n={len(eligible):,})')
    fig.tight_layout(); fig.savefig(output_dir/'nhom_nghe.png', dpi=180, bbox_inches='tight'); plt.close(fig)

    fig, axes = plt.subplots(3, 2, figsize=(16, 14)); axes = axes.flat
    for ax, family in zip(axes, groups):
        roles = [role for role in PATTERNS.get(family, {'Khác/chưa rõ': ''}) if role != 'Software khác']
        if role_counts[(family,'Chưa rõ nghề trong nhóm')]: roles.append('Chưa rõ nghề trong nhóm')
        nums = [role_counts[(family, role)] for role in roles]
        bars = ax.barh(roles[::-1], nums[::-1], color='#4f86a7')
        ax.bar_label(bars, padding=3); ax.set_xlim(0, max(nums, default=0)*1.18 or 1)
        ax.set_title(f'{family} — {group_counts[family]:,} JD'); ax.set_xlabel('Số nhóm JD')
    axes[-1].axis('off')
    fig.suptitle('Nghề chi tiết trong từng nhóm — một nghề/JD, có bằng chứng', fontsize=16)
    fig.tight_layout(rect=(0,0,1,.97)); fig.savefig(output_dir/'nghe_chi_tiet.png', dpi=180, bbox_inches='tight'); plt.close(fig)
    if stored_roles:
        skills = Counter(skill['skill'].casefold() for r in tagged
                         for skill in json.loads(r['skills_evidence'] or '[]'))
        with (output_dir/'ky_nang.csv').open('w',encoding='utf-8-sig',newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['skill','jd_count'])
            writer.writeheader(); writer.writerows({'skill':k,'jd_count':v} for k,v in skills.most_common())
        top_skills = skills.most_common(15)
        fig, ax = plt.subplots(figsize=(11,7))
        bars = ax.barh([k for k,_ in top_skills][::-1], [v for _,v in top_skills][::-1], color='#6a8e75')
        ax.bar_label(bars, padding=4); ax.set_xlim(0, max((v for _,v in top_skills),default=0)*1.18 or 1)
        ax.set_xlabel('Số nhóm JD phù hợp có nhắc kỹ năng trong nhiệm vụ/yêu cầu')
        ax.set_title('15 kỹ năng được nhắc nhiều nhất trong nội dung JD')
        fig.tight_layout(); fig.savefig(output_dir/'ky_nang.png', dpi=180, bbox_inches='tight'); plt.close(fig)
        confidence = Counter(r['role_confidence'] for r in tagged)
        labels = ['high_heuristic','title_heuristic','body_only_heuristic',
                  'ambiguous_role','ambiguous_family','generic_title_only','insufficient_evidence']
        display = {'high_heuristic':'Title + JD cùng chỉ nghề',
                   'title_heuristic':'Nghề rõ trong title',
                   'body_only_heuristic':'Chỉ JD gợi ý nghề (cần rà soát)',
                   'ambiguous_role':'Nhiều nghề trong một nhóm',
                   'ambiguous_family':'Nhiều nhóm nghề',
                   'generic_title_only':'Title chỉ rõ nhóm',
                   'insufficient_evidence':'Chưa đủ căn cứ'}
        vals = [confidence[x] for x in labels]
        fig, ax = plt.subplots(figsize=(11, 6))
        bars = ax.barh([display[x] for x in labels][::-1], vals[::-1], color='#527a9b')
        ax.bar_label(bars, padding=4); ax.set_xlim(0, max(vals)*1.18 or 1)
        ax.set_xlabel('Số nhóm JD phù hợp'); ax.set_title('Mức chứng cứ khi gán nghề (điểm quy tắc, chưa hiệu chuẩn)')
        fig.tight_layout(); fig.savefig(output_dir/'do_tin_cay_nghe.png', dpi=180, bbox_inches='tight'); plt.close(fig)
        old = Counter(role_for(r['title'])[0] for r in tagged)
        before = [old.get(g,0) for g in groups]
        fig, ax = plt.subplots(figsize=(11,6))
        y = list(range(len(groups)))
        ax.barh([v-.19 for v in y], before, height=.38, label='Chỉ title', color='#a0a8b4')
        ax.barh([v+.19 for v in y], values, height=.38, label='Title + JD + kiểm tra', color='#159f80')
        ax.set_yticks(y, groups); ax.invert_yaxis(); ax.legend()
        ax.set_xlabel('Số nhóm JD phù hợp'); ax.set_title('Phân nhóm nghề trước và sau bổ sung nội dung JD')
        fig.tight_layout(); fig.savefig(output_dir/'so_sanh_nhom_nghe.png', dpi=180, bbox_inches='tight'); plt.close(fig)
    return {'eligible':len(eligible),'group_counts':dict(group_counts),'role_counts':{f'{f} / {r}':v for (f,r),v in role_counts.items()}}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(run(args.input, args.out), ensure_ascii=False, indent=2))
