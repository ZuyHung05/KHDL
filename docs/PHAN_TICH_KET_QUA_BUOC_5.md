# Bước 5 — Cleaning QA và Deduplication

## Phạm vi và kết quả

Input là `cleaned_jds.parquet` của bước 4; checksum được kiểm tra với `cleaning_report.json`. Mọi record được giữ và có mapping:

| Chỉ số | Kết quả |
|---|---:|
| Record đầu vào / record có mapping | 9.868 / 9.868 |
| Nhóm đại diện sau exact dedup | 9.868 |
| Duplicate cluster được gộp tự động | 0 |
| Record được gộp | 0 |
| Cặp near duplicate cần review | 403 |
| GitHub issues có thể chứa nhiều vị trí | 1.077 |
| Issue có tín hiệu nhiều vị trí theo regex | 4 |

**9.868 nhóm là kết quả của quy tắc bảo thủ, không khẳng định 9.868 việc làm thực sự khác nhau.** Bốn issue có tín hiệu là kết quả của regex đơn giản, không phải toàn bộ số issue nhiều vị trí. Tất cả 1.077 issue được gắn `issue_may_contain_multiple_positions` để review và chưa tách.

## Review cleaning

Công cụ đã đối chiếu toàn bộ 50 record có `large_reduction` và 35 mẫu phân tầng: 5 record từ mỗi nguồn, chọn theo hash với seed `qa42`, ngoài tập 50. Báo cáo lưu ID, nguồn, field, số ký tự/token và kết luận từng field.

| Tập | Không phát hiện mất token hiển thị | Còn token chưa đối chiếu được |
|---|---:|---:|
| 50 record giảm mạnh | 30 | 20 |
| 35 record lấy mẫu | 33 | 2 |

Đây là **kiểm tra tự động bởi công cụ**, không phải gán nhãn của người. `no_visible_token_loss_detected` không chứng minh không mất ngữ nghĩa, không đồng nghĩa chắc chắn chỉ loại markup. `needs_review` nghĩa là token ở bản hiển thị chưa được đối chiếu, không khẳng định nội dung đã bị xóa. Các khác biệt có thể đến từ text/HTML inline hoặc dấu câu. Cần người đọc raw/clean để kết luận riêng 22 record; không sửa hoặc loại tự động.

## Exact và near duplicate

Exact dedup dùng quy tắc bảo thủ: source identity hợp lệ hoặc URL chuẩn hóa + cùng company + title + fingerprint nội dung. Các thành viên trong cluster phải tương thích với nhau về company và location khi cả hai cùng có giá trị. Riêng ID Careers@Gov tính cả platform và postingNo khi cần. Thiếu company hoặc ID đáng tin thì không gộp chỉ theo title/text. Chưa thể chứng minh các ID nguồn không tái sử dụng; cần review nếu dùng cho kết luận quan trọng.

Chọn đại diện theo thứ tự xác định: có nội dung chính, nhiều phần nội dung, tổng text dài hơn, có company, URL, source ID, cuối cùng `record_id` nhỏ nhất. Input hiện tại không có cluster gộp nên mỗi record là đại diện của chính nó.

Near dedup dùng Jaccard của **5-word shingles**, ngưỡng 0,80; chỉ so sánh trong block cùng company + title đã chuẩn hóa hoặc cùng URL. Có 628 cặp trong block được xét, 403 cặp vượt ngưỡng và giữ `needs_review`; không có block bị bỏ vì giới hạn kích thước. Các cặp ngoài block chưa được xét, nên đây không phải tìm kiếm toàn bộ near duplicates. Trùng title/description hoặc cùng template không đủ để tự gộp.

## Đối chiếu Gemini

Corpus `roles_v8` có **9.558 unique** theo quy tắc cũ. Đã nối được cả 9.868 record bằng source ID + file + snapshot SHA-256 + row index. Có **254 Gemini `jd_id` cũ liên kết tới hơn một `jd_id` mới** do quy tắc bảo thủ hơn; chênh lệch tổng record gộp là 310. Sự khác nhau không chứng minh bên nào đúng tuyệt đối.

Cột `gemini_legacy_jd_id` trong mapping phục vụ truy vết. Không tự chép nhãn Gemini sang các nhóm mới: cần xem xét các nhóm bị tách, nội dung đầu vào và phiên bản model/prompt/taxonomy trước khi tái sử dụng. Trạng thái Gemini là snapshot tại thời điểm báo cáo; xem SQLite để biết tiến độ hiện tại.

## Kiểm thử và chạy lại

Bộ test dự án: **56/56 pass** trên phiên bản cuối. Đã đối soát mỗi record có đúng một mapping, mọi mapping có provenance, và mọi cluster có một đại diện. Chạy lại trên cùng input và phiên bản cuối cho SHA-256 của cả ba artifact Parquet/CSV giống nhau; schema của các cột gốc được giữ nguyên.

Chạy từ `IT4930` sau khi cài `requirements-preparation.txt`:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.deduplicate
```

Các output: `data/staging/deduplicated_jds.parquet`, `data/staging/duplicate_mapping.parquet`, `data/reports/dedup_report.json`, `data/reports/cleaning_qa_report.json`, `data/reports/near_duplicate_candidates.csv`.
