# Phân tích kết quả bước 4 — Text Cleaning & Missing Value Handling

**Dự án:** IT4930 — M02 Data Preparation  
**Thời điểm tạo kết quả:** 21/11/2026 lúc 22:22:53 giờ Việt Nam (15:22:53 UTC)  
**Quy tắc:** `jd_text_clean_v1`  
**Nguồn số liệu:** `data/reports/cleaning_report.json` và `data/staging/cleaned_jds.parquet`.

## 1. Kết quả chính

| Chỉ số | Kết quả |
|---|---:|
| Input từ Unified JD Schema | 9.868 records |
| Output sau cleaning | 9.868 records |
| `record_id` khác nhau trong output | 9.868 |
| Record có ít nhất một trường clean thay đổi | 4.266 — 43,23% |
| Record không có trường clean thay đổi | 5.602 — 56,77% |
| Giá trị sentinel chuyển thành null ở cột clean | 3 |
| Record có cờ bất thường sau cleaning | 50 |

Đây là số **record nguồn trước dedup**. Một issue hoặc record không nhất thiết là một việc làm duy nhất. Tỷ lệ thay đổi không phải tỷ lệ lỗi: một thay đổi có thể chỉ là bỏ markup, giải mã HTML entity hoặc chuẩn hóa khoảng trắng.

Lượt thực hiện giữ các cột gốc và provenance trong output; các trường clean được ghi thêm riêng. Không lọc theo role hay quốc gia, không dedup và không gộp các phần nội dung JD.

## 2. Các trường và quy tắc đã áp dụng

Các trường có bản clean riêng gồm `job_title`, `description`, `requirements`, `raw_job_text`, `description_transformed` và `responsibilities`. Chẳng hạn, `description` được giữ nguyên, còn kết quả xử lý nằm ở `description_clean`.

Quy tắc `jd_text_clean_v1`:

1. Giải mã HTML entities, chuẩn hóa Unicode NFC và xuống dòng.
2. Loại các ký tự điều khiển và markup HTML/Markdown nhận biết được; giữ dấu heading, danh sách, nhãn và đích link dưới dạng văn bản.
3. Chuẩn hóa whitespace; chỉ loại dòng boilerplate khớp chính xác `click here to apply`.
4. Giữ riêng `description`, `requirements`, `raw_job_text` và `description_transformed`; không suy hoặc gộp field.
5. Chuyển sentinel thành null chỉ khi **toàn bộ giá trị** thuộc ngữ cảnh đã xác minh: `data_job_analysis.description_transformed`. Không thay chuỗi con trong JD.

`requirements_clean` là JSON text để giữ cấu trúc string/list/object. Những trường salary, experience, location và timezone không được tự điền. Bộ kiểm tra ký hiệu công nghệ tập trung vào `C++`, `C#`, `.NET`, `Node.js`, `CI/CD`, `AWS EC2`; đây không phải danh sách đầy đủ mọi công nghệ.

## 3. Mức độ thay đổi theo nguồn

| Nguồn | Tổng records | Records thay đổi | Tỷ lệ thay đổi |
|---|---:|---:|---:|
| `it_job_posting` | 3.101 | 1.186 | 38,25% |
| `dpl_evaluation` | 395 | 179 | 45,32% |
| `vietjobs` | 5 | 0 | 0,00% |
| `data_job_analysis` | 3.187 | 7 | 0,22% |
| `careersgovsg` | 2.078 | 1.876 | 90,28% |
| `ady201m` | 25 | 0 | 0,00% |
| `awesome_jobs_vietnam` | 1.077 | 1.018 | 94,52% |
| **Tổng** | **9.868** | **4.266** | **43,23%** |

`careersgovsg` và `awesome_jobs_vietnam` có tỷ lệ thay đổi cao. Báo cáo ghi số field thay đổi: `careersgovsg` có 1.408 description, 1.538 requirements và 1.452 responsibilities thay đổi; `awesome_jobs_vietnam` có 1.012 raw job text thay đổi. Các field này có thể cùng thuộc một record, do đó không cộng số field thay đổi để tính số record.

Tỷ lệ 0% của `vietjobs` chỉ dựa trên 5 bản ghi mẫu; nó không đại diện cho toàn bộ nguồn VietJobs.

## 4. Sentinel và missing values

Có **3 giá trị sentinel** ở `data_job_analysis.description_transformed` được chuyển thành null trong cột `description_transformed_clean`. Giá trị gốc vẫn còn trong cột `description_transformed` để truy vết.

Các missing/sentinel khác chưa được tự động xử lý ngoài phạm vi đã xác minh. Đặc biệt, 620 giá trị `Min_YOE = NA` và 25 timestamp `crawled_at` thiếu múi giờ đã được ghi nhận ở bước 3; bước 4 không tự suy kinh nghiệm hay timezone cho các giá trị này.

Không thay thế `NA`, `null` hoặc `n/a` khi chúng chỉ là một phần của đoạn văn. Không tự bổ sung description từ `raw_job_text`.

## 5. Cảnh báo giảm nội dung và kiểm tra công nghệ

Có **50 record khác nhau**, đều thuộc `careersgovsg`, có ít nhất một cờ `large_reduction`. Một record có thể có nhiều cờ:

| Cờ theo field | Số lần gắn cờ |
|---|---:|
| `large_reduction:description` | 31 |
| `large_reduction:requirements` | 11 |
| `large_reduction:responsibilities` | 11 |
| **Tổng số lần gắn cờ** | **53** |

Cờ xuất hiện khi text gốc có ít nhất 100 Unicode codepoints và text sau clean còn dưới 50% độ dài gốc. **53 là số cờ, không phải 53 record**. Việc giảm có thể do bỏ markup HTML nhưng cũng có thể che giấu mất nội dung; cần đối chiếu cột gốc và cột clean trước khi kết luận.

Không có cờ `technology_marker_reduced` trong lượt chạy này đối với sáu mẫu ký hiệu đã kiểm tra. Kết quả đó không chứng minh mọi công nghệ, phiên bản và ngữ cảnh trong toàn corpus đều được bảo toàn; cần kiểm tra mẫu bổ sung, đặc biệt 50 record có cờ giảm mạnh.

## 6. Quan hệ với kết quả chất lượng bước 3

Nhãn `quality_status` và `quality_flags` được **mang từ bước 3** sang output bước 4, không tính lại sau cleaning:

| Quality status từ bước 3 | Số records |
|---|---:|
| `usable` | 5.418 |
| `needs_review` | 4.443 |
| `unusable` | 7 |

Do đó, bảng trên không phải đánh giá chất lượng mới cho các trường clean. Cần thiết kế một lượt validation sau cleaning nếu muốn biết chất lượng thay đổi thế nào. Các nhãn này cũng không liên quan trực tiếp đến `unknown`/`needs_review` của Role Classification.

## 7. Kiểm thử và giới hạn

- Đối soát input/output: **9.868/9.868** và 9.868 ID duy nhất.
- Bộ test preparation và M01 liên quan: **18/18 pass**; gồm kiểm tra các cột gốc và tính idempotent của các trường clean trên toàn bộ output.
- Test ví dụ bảo toàn các ký hiệu `C++`, `C#`, `.NET`, `Node.js`, `CI/CD`, `AWS EC2` và số năm kinh nghiệm.
- Preflight offline của corpus Gemini `roles_v8` vẫn xác nhận **9.558 unique và 5.915 candidates**. Kết quả này không chứng minh chất lượng nhãn Gemini; pipeline Gemini hiện chưa đọc file cleaned này.
- Các giá trị có `clean_error` hoặc `content_became_empty` cần review nếu xuất hiện ở lượt sau; lượt hiện tại không ghi nhận các cờ đó.
- Bước này không tạo dataset cuối, không kiểm toán ngữ nghĩa toàn bộ JD và không kết luận các record có thể dùng cho EDA hoặc huấn luyện.

## 8. Bước tiếp theo đề xuất

1. Review 50 record có `large_reduction`: so sánh gốc–clean và ghi nhận xem phần giảm là markup hay nội dung thực.
2. Kiểm tra mẫu phân tầng từ từng nguồn, gồm danh sách requirements và issue body, để phát hiện ký hiệu hoặc cấu trúc bị biến đổi ngoài sáu mẫu công nghệ.
3. Thiết kế validation sau cleaning và dedup; giữ mapping từ từng `record_id` về JD đại diện.
4. Khi nối kết quả Gemini, đối chiếu đúng snapshot/corpus và giữ nhãn LLM là đề xuất; không mặc định coi các record bước 4 đã có nhãn Gemini.

## 9. File liên quan và tái tạo

- [Cleaning report](../data/reports/cleaning_report.json): số liệu, checksum và định nghĩa máy đọc được.
- [Cleaned JD Parquet](../data/staging/cleaned_jds.parquet): cột gốc, cột clean và flags theo record.
- [Validation bước 3](PHAN_TICH_KET_QUA_BUOC_3.md): baseline chất lượng trước cleaning.
- [Unified schema và hướng dẫn](UNIFIED_JD_SCHEMA.md): schema và quy tắc sử dụng.
- [Mã cleaning](../src/preparation/cleaning.py): quy tắc `jd_text_clean_v1`.

Từ thư mục `IT4930`, chạy:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.cleaning
```

Báo cáo này phản ánh lượt chạy có output SHA-256 `6c79653b546c7913087be89396edee459e68ab1c2c46f076713353cabca73648`. Nếu chạy lại với input hoặc quy tắc mới, cần cập nhật các số liệu và checksum trong tài liệu này.
