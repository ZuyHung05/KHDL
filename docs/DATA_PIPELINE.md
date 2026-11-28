# Quy trình từ crawl tháng đến kết quả nghiên cứu

## 1. Crawl tháng

GitHub Actions chạy lúc 09:17 ngày đầu tháng, giờ Việt Nam. `monthly_crawl.py` mở **một Chrome ẩn**, lần lượt tìm các nghề đang theo dõi trên TopCV và ITviec; mặc định tối đa 2 trang/nghề/nguồn, 3 trang/truy vấn, 15 JD chi tiết/nghề/nguồn. URL trùng trong cùng run bị bỏ qua. Mỗi JD chỉ được ghi vào `jobs.jsonl` sau khi tách được description. Khi website trả 403/429/challenge, crawler ghi sự kiện rồi dừng nguồn đó.

Thư mục `data/monthly_crawl/<run-id>/` gồm:

| Tệp | Nội dung |
|---|---|
| `plan.json` | Ngày, nguồn, nghề, giới hạn trang và JD |
| `jobs.jsonl` | JD có description, title, URL, công ty, địa điểm, nhiệm vụ, yêu cầu, quyền lợi khi trích được |
| `errors.jsonl` | Các URL lỗi tách nội dung hoặc tải trang, nếu có |
| `events.jsonl` | Số card theo trang và lần bị chặn, nếu có |
| `summary.json` | Tổng số JD, nguồn, trạng thái và nghề sau preparation |
| `prepared/` | Release preparation của **riêng tháng đó**, gồm `jds_all.csv`, `jds_eligible.csv`, `jds_eligible_labeled.csv` |
| `chrome-profile/` | Phiên Chrome tạm, không upload artifact |

Workflow GitHub chỉ upload `plan.json`/`summary.json` trên repo public. Trên repo private, nó upload thêm `jobs.jsonl`, log và `prepared/`. Sau preparation, workflow xuất JD phù hợp đã che thông tin liên hệ, gộp theo URL/ID TopCV vào `datasets/eligible_jds.csv` và commit trên nhánh chạy workflow nếu tệp đổi. Artifact không phải lưu trữ vĩnh viễn; CSV công bố là tập tích lũy, không phải lưu trữ raw hoặc tin đang tuyển còn hiệu lực.

## 2. Preparation (một pipeline)

`src/preparation/pipeline.py` đọc đầu vào Parquet theo schema chuẩn hoặc JSONL crawler, kiểm tra định dạng và ghi SHA-256 từng tệp. Với TopCV, nó khôi phục phần mô tả/yêu cầu từ HTML đã biến thành văn bản; với ITviec, dùng các phần JD đã tách trong crawler. Dữ liệu cũ đã biến đổi hoặc chưa đầy đủ vẫn được phân tích nếu còn nội dung, kèm cờ chất lượng.

Tiếp theo pipeline đánh giá IT/ngoài IT và Việt Nam/ngoài Việt Nam/chưa rõ; gộp bản trùng theo URL và ID TopCV; gán `role_family`, một `primary_role`, độ tin cậy theo quy tắc và kỹ năng với bằng chứng từ title, nhiệm vụ, yêu cầu. Thiếu căn cứ thì giữ `unknown`. Cuối cùng nó tạo ba CSV chia sẻ có nội dung JD, CSV theo trạng thái, báo cáo và biểu đồ. Mọi release có manifest checksum và không bị ghi đè nếu input/rule khác.

## 3. Gộp dữ liệu giữa các tháng trên máy cá nhân

Runner GitHub không có `data/inputs/legacy_import_20261127.parquet`, nên **release preparation trong artifact tháng chỉ chứa JD của tháng đó**. CSV công bố ở `datasets/eligible_jds.csv` được gộp từng tháng, nhưng các dòng cũ không được đánh giá lại theo quy tắc mới. Muốn tái tính toàn corpus, sau khi tải các artifact private về, đặt `jobs.jsonl` của mỗi tháng trong `data/monthly_crawl/` và chạy:

```bash
.venv/bin/python -m src.pipeline prepare \
  --input data/inputs/legacy_import_20261127.parquet \
  --input data/monthly_crawl/2026-12/jobs.jsonl \
  --input data/monthly_crawl/2027-01/jobs.jsonl \
  --run-id all_2027_01 --execute
```

Lần sau, liệt kê lại **tất cả** batch JSONL muốn đưa vào corpus. Pipeline gộp URL trùng và tạo lại `jds_all.csv`, `jds_eligible.csv`, `jds_eligible_labeled.csv` trong release mới; không nối dòng mù vào CSV cũ. Nếu quy tắc đổi, chọn `run-id` mới và chạy lại từ cùng input để so sánh công bằng.

## 4. Theo dõi nghề còn thiếu

`targeted_role_crawl.py` đọc `master_jds.parquet` hiện hành, so sánh từng nghề với mục tiêu 80, viết `role_priority.csv/.md/.png`, crawl bổ sung theo mức thiếu rồi chạy lại pipeline. Checkpoint gồm `state.json`, `jobs.jsonl`, `events.jsonl`, `errors.jsonl`. Nó dừng khi đủ 80, hết truy vấn đã cấu hình, bị chặn hết nguồn hoặc hết số vòng cho phép; **không lặp vô hạn để tạo số liệu giả**.

```bash
.venv/bin/python -m src.collection.targeted_role_crawl \
  --run-dir data/targeted_crawl/pilot_cloud_20261127 \
  --baseline-input data/inputs/legacy_import_20261127.parquet \
  --baseline-run data/curated/preparation/current/master_jds.parquet \
  --target 80 --max-cycles 16 --refresh-searches --retry-blocked
```

## 5. Dùng kết quả

Để chia sẻ với thành viên, dùng `jds_all.csv` khi cần kiểm toán mọi trạng thái, `jds_eligible.csv` cho EDA JD phù hợp, và `jds_eligible_labeled.csv` khi phân tích phân bố nghề. Ba tệp đều có title, URL, nguồn, nội dung JD, trạng thái, nghề và cờ chất lượng. `eligible.csv` cũ chỉ là bảng trạng thái ngắn, không có full text. Xem `needs_review.csv`, `audit_150.csv`, `role_confidence` và `content_quality_caveat` trước khi huấn luyện mô hình. Danh sách chi tiết tệp release ở [CURATED_DATA_CONTRACT.md](CURATED_DATA_CONTRACT.md).
