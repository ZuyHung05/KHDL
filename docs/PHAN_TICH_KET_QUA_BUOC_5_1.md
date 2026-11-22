# Bước 5.1 — Deduplication Audit & Reconciliation

## Kết quả và phạm vi

Audit dùng cùng 9.868 records của `cleaned_jds.parquet`. Kết quả `dedup_v2`:

| Chỉ số | V1 | V2 |
|---|---:|---:|
| Records đầu vào / có mapping | 9.868 / 9.868 | 9.868 / 9.868 |
| Nhóm đại diện | 9.868 | 9.427 |
| Duplicate clusters | 0 | 441 |
| Records được gộp | 0 | 441 |
| Near candidates còn trong output | 403 | 29 |

441 cluster V2 đều có hai thành viên; cả 441 phép gộp dựa trên **cùng ID tin TopCV dạng số trong đường dẫn**, title đã chuẩn hóa trùng và không có xung đột company/location khi cả hai giá trị hiện diện. Tham số theo dõi không được dùng làm ID. Quy tắc này là giả định dựa trên định dạng URL đã quan sát, không phải kiểm toán của TopCV về tái sử dụng ID.

**9.427 là số nhóm theo chính sách hiện tại**, không phải số việc làm thực tế đã xác minh tuyệt đối. 1.077 GitHub issues vẫn được đánh dấu có thể chứa nhiều vị trí và không tự tách.

## Audit 403 cặp near của V1

Tất cả 403 cặp được phân loại bằng quy tắc và giữ trong `near_duplicate_audit.csv`:

| Nhãn | Cặp | Bằng chứng / giới hạn |
|---|---:|---|
| `confirmed_duplicate` | 369 | Cùng ID tin TopCV dạng số, cùng title, không xung đột company/location. Đây là kết luận theo quy tắc định danh, chưa có gold của con người. |
| `distinct` | 8 | ID tin TopCV khác nhau: record của các bài đăng khác nhau. Vẫn có thể là cùng vị trí được đăng lại. |
| `uncertain` | 26 | Similarity cao hoặc ID khác không đủ xác nhận cùng vị trí. |

Tổng cộng 441 record được gộp trong V2, nhiều hơn 369 cặp confirmed trong tập 403 vì 72 cặp gộp có cùng ID tin nhưng không thuộc tập near V1 đạt ngưỡng Jaccard 0,80. Similarity không được dùng để tự xác nhận duplicate. `near_duplicate_audit_sample.json` lưu tối đa 5 cặp mỗi nhóm, chọn theo hash seed cố định; phân loại mẫu là bằng quy tắc, chưa phải gán nhãn độc lập. Danh sách near sau khi gộp còn 29 cặp; không đồng nghĩa chỉ còn 29 khả năng trùng trên toàn corpus vì thuật toán chỉ xét các block đã định nghĩa.

## Vì sao Gemini cũ là 9.558 còn V2 là 9.427?

Baseline Gemini gộp theo URL đã chuẩn hóa hoặc fingerprint title/company/description khi thiếu URL; xử lý khác V2 về tham số theo dõi và thiếu thông tin. Đối chiếu bằng source ID, file, SHA-256 và row index tìm đủ 9.868 record ở cả hai tập.

- Có **254 `jd_id` legacy** trải trên nhiều nhóm V2: **242** nhóm từ `data_job_analysis` thiếu cả company lẫn URL, **12** nhóm từ `careersgovsg` thiếu URL. Các nhóm này chưa có bằng chứng đủ để gộp tự động theo V2; chi tiết ID và các thành viên trong `legacy_dedup_audit.json`.
- V2 gộp 441 cặp TopCV mà Gemini legacy đang coi là các ID khác nhau, do URL khác tham số theo dõi. Có **441 nhóm V2 chứa nhiều legacy IDs**.
- Chênh lệch số học: `9.558 + 310 record legacy từng gộp - 441 record V2 gộp = 9.427`. Đây là đối soát số lượng, không chứng minh mọi quyết định cũ hoặc mới là ground truth.

Mapping lưu `gemini_legacy_jd_id` để truy vết. Không tự chuyển nhãn Gemini vào cluster mới: 254 nhóm legacy bị tách và 441 nhóm V2 hợp nhiều ID cũ đều cần đối chiếu input/model/nhãn và xử lý xung đột trước khi tái sử dụng.

## Audit 22 record cleaning

Đã đối chiếu 22 record từng không khớp token bằng phép kiểm tra độc lập các ký tự chữ/số và `+`, `#` trong text hiển thị, giữ thứ tự. Cả **22/22 không phát hiện ký tự thuộc tập này bị mất**. Chi tiết từng ID và field nằm tại `cleaning_qa_audit.json`.

Đây là bằng chứng tự động có giới hạn: chưa xác nhận dấu câu, URL, cấu trúc trình bày hoặc ngữ nghĩa; **không khẳng định 22/22 chỉ mất markup hoặc không có mất nội dung thực**. Không phát hiện bằng chứng đủ để sửa quy tắc cleaning; giữ nguyên file clean, quality flags và 22 record chờ review con người nếu dùng làm kết luận. Không có gold hoặc gán nhãn thủ công được tuyên bố.

## Kiểm thử và thực thi

- Unit tests bao gồm nhận diện TopCV ID, company xung đột, URL ID khác, template giống nhưng danh tính khác, gần giống không tự gộp, chọn đại diện và audit ký tự.
- Bộ test toàn dự án: **60 pass** tại lần chạy sau thay đổi quy tắc; kiểm tra lại sau mọi thay đổi tiếp theo.
- Đối soát 9.868 `record_id` độc nhất trong mapping; 9.427 đại diện và 441 `merged_exact`; provenance từng thành viên được lưu. Raw và corpus Gemini giữ nguyên.
- Lệnh tái tạo (đọc audit baseline V1 đã lưu):

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.audit_reconciliation
```

Output chính: `deduplicated_jds.parquet`, `duplicate_mapping.parquet`, `dedup_report.json`, `dedup_reconciliation_report.json`, `legacy_dedup_audit.json`, `near_duplicate_audit.csv`, `near_duplicate_audit_sample.json`, `cleaning_qa_audit.json`. File `near_duplicate_candidates.csv` là các cặp cần xem xét **sau** V2; `near_duplicate_audit.csv` bảo toàn 403 cặp V1 và phân loại của chúng.
