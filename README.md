# KHDL — Thu thập và chuẩn bị JD IT

Một luồng hiện hành: **crawl TopCV/ITviec → lấy JD chi tiết → preparation → báo cáo và biểu đồ**. Nhãn nghề và trạng thái phù hợp là nhãn quy tắc, cần kiểm toán mẫu trước khi dùng làm ground truth.

## Cấu trúc

| Thư mục | Vai trò |
|---|---|
| `crawlers/` | Trình duyệt chung và crawler trang danh sách TopCV |
| `src/collection/` | Crawl theo nghề, lịch crawl tháng và tách JD chi tiết |
| `src/preparation/` | Pipeline duy nhất: chuẩn hoá đầu vào, đánh giá phạm vi, gộp URL, gán nhóm/nghề/kỹ năng, xuất báo cáo |
| `src/pipeline.py` | CLI để chạy preparation trên tệp đầu vào khai báo rõ |
| `configs/crawlers.yaml` | Cấu hình trình duyệt và trang TopCV |
| `.github/workflows/` | Kiểm thử offline và crawl theo lịch tháng |
| `tests/` | Chỉ kiểm thử các chức năng còn duy trì |
| `data/` | Dữ liệu chạy pipeline tại máy, không đưa lên Git |
| `datasets/eligible_jds.csv` | Bản JD phù hợp được công bố cho thành viên phân tích |

Kiến trúc và hợp đồng dữ liệu: [ARCHITECTURE.md](docs/ARCHITECTURE.md), [DATA_PIPELINE.md](docs/DATA_PIPELINE.md), [CURATED_DATA_CONTRACT.md](docs/CURATED_DATA_CONTRACT.md). Các phần đã xoá và số liệu đối chiếu: [CLEANUP_20261127.md](docs/CLEANUP_20261127.md).

## Cài đặt

```bash
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m playwright install chrome
.venv/bin/python -m pytest -q
```

## Crawl và preparation

```bash
# Chạy một snapshot mới bằng Chrome ẩn (mỗi website được giới hạn trang/JD).
.venv/bin/python -m src.collection.monthly_crawl \
  --out-dir data/monthly_crawl/2026-12

# Chạy lại toàn bộ corpus: bản nhập lịch sử và một hay nhiều batch crawl mới.
.venv/bin/python -m src.pipeline prepare \
  --input data/inputs/legacy_import_20261127.parquet \
  --input data/monthly_crawl/2026-12/jobs.jsonl \
  --run-id all_2026_12 --execute

# Liệt kê các bản kết quả đã tạo.
.venv/bin/python -m src.pipeline status
```

Mỗi lần `prepare` tạo thư mục bất biến `data/curated/preparation/<run-id>/`, gồm ba CSV chia sẻ: `jds_all.csv`, `jds_eligible.csv`, `jds_eligible_labeled.csv`. Nếu thêm tháng tiếp theo, khai báo **toàn bộ** batch JSONL cần tính cùng bản nhập lịch sử. Không tự nối dữ liệu giữa các runner GitHub. Đầu vào local cũ đã được giữ ở `data/inputs/legacy_import_20261127.parquet`; đây là **văn bản đã biến đổi**, không phải HTML gốc. JSONL crawl lịch sử được lưu ở `data/raw/crawled_history/`.

Release tổng hợp hiện có cho nhóm: `data/curated/preparation/share_20261128/` (10.125 JD; 4.467 phù hợp; 3.279 phù hợp và đã có nghề chính). Xem `manifest.json` cùng thư mục khi trao đổi tệp để kiểm tra phiên bản và checksum.

## Dataset chia sẻ cho nhóm

[**datasets/eligible_jds.csv**](datasets/eligible_jds.csv) là một tệp CSV UTF-8 có BOM, **4.467 JD duy nhất** từ release `share_20261128` (28/11/2026). Mỗi dòng có `jd_id`, nguồn và URL gốc, title, công ty, địa điểm, trạng thái Việt Nam/IT, nhóm nghề, nghề chính, mức chứng cứ gán nghề, kỹ năng và nội dung nhiệm vụ/yêu cầu/quyền lợi trong `jd_text`. Tất cả dòng đều có `eligibility_status=eligible` theo quy tắc hiện tại; **1.188 dòng có `primary_role=unknown`** nên chưa dùng làm nhãn nghề. Có 1.757 dòng `transformed_text`, 1.048 `partial_jd` và 1.662 `full_jd`; các trạng thái này đánh dấu chất lượng văn bản, không chứng minh HTML gốc đầy đủ.

Nguồn theo `source_id`: `it_job_posting` 2.076, `data_job_analysis` 1.757, `dpl_evaluation` 262, TopCV 262, ITviec 110. `source_url` giúp truy xuất bài gốc khi còn tồn tại. Bản công bố đã thay **194 email và 65 số điện thoại** trong nội dung bằng nhãn giữ chỗ; bản gốc vẫn ở `data/` local. Đây là nhãn tự động phục vụ nghiên cứu, chưa phải ground truth; kiểm toán mẫu trước khi huấn luyện hoặc kết luận thị trường. Nội dung đến từ bên thứ ba; thành viên cần kiểm tra điều kiện sử dụng của từng nguồn trước khi tái phát hành ở nơi khác.

Ví dụ đọc bằng Python:

```python
import pandas as pd
jobs = pd.read_csv('datasets/eligible_jds.csv', encoding='utf-8-sig')
known_roles = jobs[jobs['primary_role'] != 'unknown']
```

CSV này bắt đầu từ release `share_20261128`. Mỗi tháng, workflow chạy preparation cho batch mới, che thông tin liên hệ, gộp JD phù hợp vào tệp này theo URL/ID TopCV và commit nếu nội dung đổi. Khi URL trùng, bản có nội dung đầy đủ hơn được giữ lại. Vì GitHub runner không có toàn bộ đầu vào lịch sử, đây là **tập JD phù hợp tích lũy theo các lần chạy**, không phải bản chạy lại toàn corpus theo quy tắc mới. Tin cũ có thể đã hết hạn; kiểm tra `source_url` trước khi xem là vị trí đang tuyển. Nếu quy tắc preparation thay đổi, cần chạy lại toàn bộ input trên máy và thay thế bản công bố sau khi kiểm toán.

## Lịch GitHub Actions

Workflow [monthly-job-crawl.yml](.github/workflows/monthly-job-crawl.yml) chạy **09:17 ngày 1 hằng tháng giờ Việt Nam**, hoặc chạy thủ công bằng `workflow_dispatch`. Nó dùng một phiên Chrome ẩn, dừng nguồn khi gặp Cloudflare, chạy cùng pipeline preparation trên snapshot tháng và lưu `summary.json`. Nếu có JD phù hợp mới, workflow cập nhật `datasets/eligible_jds.csv` và push bằng `GITHUB_TOKEN` (cần quyền ghi nhánh trong cấu hình repository). Artifact JD đầy đủ của tháng chỉ được tải lên khi repository private; GitHub artifact hết hạn tối đa sau 90 ngày. Lịch chỉ hoạt động khi workflow nằm trên default branch. Nếu toàn bộ nguồn bị chặn hoặc không tải được JD, run báo lỗi và không cập nhật CSV.

Chưa bật LLM tự động. Code phân loại Gemini cũ và checkpoint gắn với pipeline đã bỏ không còn trong luồng hiện hành. Muốn gán nhãn `unknown` bằng LLM về sau cần kho lưu riêng, khóa API, hạn mức token và kiểm toán nhãn.
