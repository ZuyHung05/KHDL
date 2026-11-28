"""Figures and narrative for the maintained preparation pipeline."""
from __future__ import annotations

import json
from collections import Counter


def render(dest, summary):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    labels = ['Phù hợp theo quy tắc', 'Cần xem xét', 'Không phù hợp theo quy tắc']
    keys = ['eligible', 'needs_review', 'not_eligible']
    values = [summary['counts'].get(k, 0) for k in keys]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6))
    bars = axes[0].barh(labels, values, color=['#159f80', '#e4a63e', '#d75e61'])
    axes[0].invert_yaxis(); axes[0].bar_label(bars, padding=4)
    axes[0].set_title('Trạng thái eligibility'); axes[0].set_xlabel('Số nhóm JD')
    source_order = sorted(summary['by_source'])
    left = [0] * len(source_order)
    for key, color in zip(keys, ['#159f80', '#e4a63e', '#d75e61']):
        v = [summary['by_source'][s].get(key, 0) for s in source_order]
        axes[1].barh(source_order, v, left=left, label=key, color=color)
        left = [a+b for a,b in zip(left,v)]
    axes[1].invert_yaxis(); axes[1].legend(fontsize=8)
    axes[1].set_title('Trạng thái theo nguồn'); axes[1].set_xlabel('Số nhóm JD')
    fig.suptitle('JD preparation — nhãn tự động, cần kiểm toán mẫu', fontsize=15)
    fig.tight_layout(); fig.savefig(dest/'trang_thai_jd.png', dpi=160, bbox_inches='tight'); plt.close(fig)

    reasons = Counter(summary['review_reasons'])
    fig, axes = plt.subplots(1, 2, figsize=(15, 5))
    trans = sorted(summary['transitions'].items(), key=lambda x:-x[1])[:12]
    bars = axes[0].barh([k for k,v in trans][::-1], [v for k,v in trans][::-1], color='#597ca6')
    axes[0].bar_label(bars, padding=3); axes[0].set_title('Trạng thái đầu vào → kết quả hiện tại')
    bars = axes[1].barh(list(reasons)[::-1], list(reasons.values())[::-1], color='#e4a63e')
    axes[1].bar_label(bars, padding=3); axes[1].set_title('Lý do review (có thể chồng lấn)')
    fig.tight_layout(); fig.savefig(dest/'ly_do_va_chuyen_nhan.png', dpi=160, bbox_inches='tight'); plt.close(fig)

    lines = ['# Báo cáo preparation', '', f"Đầu vào: {summary['input_groups']:,} bản ghi từ các tệp được khai báo; đại diện {summary['input_raw_records_represented']:,} bản ghi nguồn.",
             f"Sau đối sánh: {summary['output_groups']:,} nhóm.", '', '| Trạng thái | Số nhóm |', '|---|---:|']
    lines += [f'| {k} | {summary["counts"].get(k,0):,} |' for k in keys]
    lines += ['', '## TopCV', '', f"Trạng thái tách nội dung: `{json.dumps(summary['topcv_parse'],ensure_ascii=False)}`.",
              'Nhãn tự động là đề xuất. Những tin không phục hồi được JD chính vẫn nằm trong hàng đợi review.',
              'Các bản `partial_jd` và `transformed_text` được phép phân tích theo lựa chọn của dự án; `content_quality_caveat` giữ rõ giới hạn của nội dung.',
              '`careersgovsg` thiếu địa điểm ở nhiều bản ghi. Khi không có bằng chứng trái ngược, quốc gia Singapore được suy từ phạm vi nguồn đã ghi trong registry; `evidence.country_basis` đánh dấu đây là suy luận cấp nguồn.',
              '', '## Giới hạn', '', 'Bản nhập lịch sử giữ nguyên nội dung đã xử lý trước đây; không có HTML gốc để phục hồi nội dung từng nguồn.',
              'Đối sánh tự gộp URL chuẩn giống nhau; ID TopCV chỉ gộp khi title, công ty và địa điểm khớp. Tin đăng lại dưới ID khác có thể còn trùng.',
              'Chưa có gold độc lập hoặc xác nhận người; view eligible cần kiểm tra mẫu trước khi dùng làm số liệu nghiên cứu.',
              'CSV theo trạng thái chứa URL, nguồn và lý do. `master_jds.parquet` giữ nội dung và bằng chứng.']
    (dest/'BAO_CAO.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
