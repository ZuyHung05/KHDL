# Hợp đồng đầu vào và đầu ra preparation

## Đầu vào

Lệnh `python -m src.pipeline prepare --input PATH ... --run-id ID --execute` nhận:

1. Parquet nhập lịch sử với `record_id`, `source_id`, `title`, `duties`, `requirements`, `parse_status`; các trường `source_url`, `company`, `location`, `benefits`, trạng thái cũ và `member_count` được giữ nếu có.
2. JSONL crawler với `site` (`topcv` hoặc `itviec`), `job_url`, `title`, `company`, `location`, `description`; `duties`, `requirements`, `benefits`, `parse_status` được dùng nếu crawler đã tách.

Tệp không tồn tại, loại không hỗ trợ hoặc dòng crawler thiếu URL hợp lệ làm run lỗi. `data/inputs/legacy_import_20261127.parquet` là bản nhập lịch sử từ release cuối trước khi dọn code; `data/inputs/manifest.json` ghi checksum. Nó không thay thế HTML gốc.

## Đầu ra

Thư mục `data/curated/preparation/<run-id>/` có:

| Tệp | Cách dùng |
|---|---|
| `master_jds.parquet` | Một dòng/JD sau gộp, giữ nội dung, nhãn, bằng chứng, cờ chất lượng và `group_members` |
| `jds_all.csv` | Bản chia sẻ đầy đủ: một dòng/JD, có `jd_text`, nhãn và trạng thái |
| `jds_eligible.csv` | Chỉ JD phù hợp; vẫn giữ `primary_role=unknown` để không đánh mất dữ liệu |
| `jds_eligible_labeled.csv` | JD phù hợp **và** đã xác định một nghề chính; dùng cho phân tích phân bố nghề |
| `duplicate_mapping.parquet` | Mapping record đầu vào → đại diện |
| `eligible.csv` | JD phù hợp theo quy tắc |
| `needs_review.csv` | JD cần xem xét và lý do |
| `not_eligible.csv` | JD ngoài phạm vi theo quy tắc |
| `audit_150.csv` | Mẫu cố định để người đánh nhãn và ghi chú |
| `jd_roles.csv`, `nhom_nghe.csv`, `nghe_chi_tiet.csv`, `ky_nang.csv` | Bảng nghề và kỹ năng cho EDA |
| `trang_thai_jd.png`, `nhom_nghe.png`, `nghe_chi_tiet.png`, `ky_nang.png`, `do_tin_cay_nghe.png`, `so_sanh_nhom_nghe.png`, `ly_do_va_chuyen_nhan.png` | Biểu đồ |
| `summary.json`, `BAO_CAO.md` | Tổng hợp và giới hạn |
| `manifest.json` | SHA-256 của từng đầu vào, code quy tắc và từng tệp kết quả |

`eligibility_status ∈ {eligible, needs_review, not_eligible}`. `role_family` và `primary_role` có thể là `unknown` dù JD `eligible`; không được tự ép vào nghề khác. `role_confidence` là mức chứng cứ quy tắc, chưa phải xác suất hiệu chuẩn. `content_quality_caveat` đánh dấu `partial_jd`/`transformed_text`.

Ba CSV chia sẻ có cùng cột: `release_id`, `jd_id`, `source_id`, `source_url`, `title`, `company`, `location`, `geography_status`, `domain_status`, `eligibility_status`, `role_family`, `primary_role`, `role_confidence`, `role_confidence_score`, `content_status`, `content_quality_caveat`, `parse_status`, `review_reasons`, `skills`, `duties`, `requirements`, `benefits`, `jd_text`, `member_count`. Mã hoá UTF-8 có BOM để Excel đọc tiếng Việt; `jd_text` giữ xuống dòng và được CSV quote đúng chuẩn. Không có ngày đăng nếu nguồn không cung cấp đáng tin cậy.

CSV giữ nguyên văn bản dài. Trong release `share_20261128` có một JD dài hơn giới hạn 32.767 ký tự của một ô Excel; Python, R hoặc công cụ đọc CSV không có giới hạn ô này sẽ giữ đầy đủ nội dung. Không chỉnh sửa CSV đã phát hành; tạo `run-id` mới khi thêm dữ liệu hoặc đổi quy tắc.

Một `run-id` đã tồn tại chỉ được tái sử dụng khi fingerprint đầu vào và quy tắc y hệt; thay đổi thì phải tạo run-id mới. Đây là release bất biến phục vụ so sánh và truy xuất nguồn gốc.
