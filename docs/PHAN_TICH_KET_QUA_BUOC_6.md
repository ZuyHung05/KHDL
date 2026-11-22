# Phân tích kết quả bước 6 — Field Normalization

Nguồn: `data/staging/deduplicated_jds.parquet`, 9.427 đại diện theo `dedup_v2`; dữ liệu đầu vào ánh xạ về 9.868 record nguồn. Kết quả `field_normalization_v1` chứa đủ **9.427/9.427** nhóm và bảo toàn các cột đầu vào. Không lọc theo quốc gia hay role.

## Coverage

| Cột chuẩn hóa | Có giá trị | Chưa xác định | Coverage |
|---|---:|---:|---:|
| Location | 6.025 | 3.402 | 63,91% |
| Country | 371 | 9.056 | 3,94% |
| Experience min | 4.235 | 5.192 | 44,92% |
| Experience max | 1.605 | 7.822 | 17,03% |
| Seniority | 368 | 9.059 | 3,90% |
| Employment type | 5.399 | 4.028 | 57,27% |
| Work arrangement | 806 | 8.621 | 8,55% |
| Posted at | 2.078 | 7.349 | 22,04% |

Các số là coverage trên 9.427 nhóm, không phải độ chính xác. Báo cáo JSON có `input_nonempty` và số/tỷ lệ sau chuẩn hóa cho từng nguồn. Field nguồn liên quan có nội dung chưa chắc đủ bằng chứng: location có thể chỉ là thành phố mà không có country; remote flag bằng 0 không chứng minh on-site. Dictionary địa danh là tập khởi tạo, không bao phủ toàn bộ địa chỉ.

## Cờ cần review

- 3.187 nhóm có `seniority_source_codes_unmapped` vì các mã L1–L4 chưa rõ ngữ nghĩa; không chuyển thành seniority.
- 1.757 nhóm có `work_arrangement_unrecognized`, chủ yếu do field nguồn ghi Full-time/Part-time là lịch làm việc thay vì remote/on-site.
- 421 nhóm có `employment_multiple`; danh sách giá trị được giữ và cần đọc theo ngữ cảnh nguồn.
- 240 nhóm có cờ `experience_without_source_text`, 169 có `experience_zero_range_ambiguous`; không coi các giá trị số mặc định là bằng chứng kinh nghiệm.
- 64 giá trị max experience nằm ngoài khoảng 0–60 được gắn cờ; không ép vào khoảng.

Các cờ có thể cùng xuất hiện ở một nhóm và không nên cộng để tính số nhóm khác nhau. Status `needs_review` chỉ cho biết ít nhất một field có cảnh báo; các field khác trong cùng dòng vẫn có thể được chuẩn hóa.

## Kiểm tra và giới hạn

- Đối soát **9.427/9.427** nhóm, **9.868** record trong mapping; mỗi nhóm có một đại diện và tập thành viên khớp mapping.
- Toàn bộ cột đầu vào được đối chiếu bằng Arrow equality và giữ nguyên. Chạy lại cùng input và dictionary cho SHA-256 Parquet giống nhau.
- Bộ test toàn dự án: **65 pass**. Không chạy Gemini API; normalization không thay đổi corpus Gemini.
- Chưa có gold để đo độ chính xác normalization. Không mặc định location, timezone, seniority hoặc năm kinh nghiệm khi không đủ chứng cứ; nhãn nguồn có thể đã được suy luận trước đó.

Xem [quy tắc normalization](FIELD_NORMALIZATION_RULES.md), [báo cáo máy đọc](../data/reports/normalization_report.json) và [dataset staging](../data/staging/normalized_jds.parquet). Kết quả chỉ là bước 6; chưa dedup lại, lọc role/quốc gia hoặc phát hành curated cuối.
