# Phân tích kết quả bước 3 — Structural Validation & Missing Data

**Dự án:** IT4930 — M02 Data Preparation  
**Thời điểm tạo dữ liệu báo cáo:** 21/11/2026 22:04:51 giờ Việt Nam (15:04:51 UTC)  
**Phạm vi:** `data/staging/unified_jds.parquet`, được tạo từ snapshot hiện hành của 7 nguồn.  
**Dấu vân tay input SHA-256:** `0e1fd5ffe408bae664d513ffa9b12022034c49ca0a18311e09e195018dc9ef63`.

## 1. Kết quả chính

Bước 3 kiểm tra **9.868 record nguồn** và tạo **9.868 dòng quality flags**, với 9.868 `record_id` khác nhau. Đây là số record trước dedup; một record nguồn không nhất thiết tương ứng một việc làm duy nhất. Kết quả đối soát 427 tổ hợp nguồn–trường trong báo cáo missing đều khớp tổng số record của từng nguồn.

| Trạng thái chất lượng | Số record | Tỷ lệ trên 9.868 |
|---|---:|---:|
| `usable` | 5.418 | 54,90% |
| `needs_review` | 4.443 | 45,02% |
| `unusable` | 7 | 0,07% |
| **Tổng** | **9.868** | **100,00%** |

Các trạng thái trên đánh giá khả năng sử dụng **nội dung đầu vào**, không phải kết quả Role Classification. `usable` cũng chưa chứng minh JD đầy đủ, thuộc IT hoặc phù hợp để đưa vào mọi phân tích.

## 2. Quy tắc phân loại đang sử dụng

- **`usable`:** có title hữu ích và description dài từ 100 ký tự, hoặc raw JD text dài từ 100 ký tự đối với nguồn khác GitHub Issues, đồng thời không có lỗi cấu trúc.
- **`needs_review`:** có nội dung nhưng title thiếu/sai, có lỗi cấu trúc, description/raw text quá ngắn, chỉ có requirements, chỉ có văn bản đã biến đổi, hoặc là GitHub issue body có thể chứa nhiều vị trí.
- **`unusable`:** không có nội dung hữu ích ở cả description, requirements, raw job text và description transformed.

Thiếu requirements hoặc salary không tự làm record không hợp lệ. Ngưỡng 100 ký tự là **heuristic**, chưa được đánh giá bằng mẫu gán nhãn; độ dài đủ không đảm bảo nội dung thực sự là JD chất lượng.

## 3. Kết quả theo nguồn

| Nguồn | Tổng | Usable | Needs review | Unusable | Nhận xét chính |
|---|---:|---:|---:|---:|---|
| `it_job_posting` | 3.101 | 3.100 | 1 | 0 | Một description dưới ngưỡng 100 ký tự. |
| `dpl_evaluation` | 395 | 395 | 0 | 0 | Dùng raw JD text; requirements có kiểu mảng. |
| `vietjobs` | 5 | 5 | 0 | 0 | Chỉ là file mẫu 5 record, không đại diện bộ đầy đủ. |
| `data_job_analysis` | 3.187 | 0 | 3.184 | 3 | Dùng `JD_Trans` đã biến đổi; 3 record không có nội dung hữu ích. |
| `careersgovsg` | 2.078 | 1.893 | 181 | 4 | Có description ngắn hoặc chỉ có requirements; dữ liệu Singapore nhiều ngành. |
| `ady201m` | 25 | 25 | 0 | 0 | Đủ nội dung theo heuristic; 25 thời điểm thu thập thiếu timezone. |
| `awesome_jobs_vietnam` | 1.077 | 0 | 1.077 | 0 | Một issue có thể chứa nhiều vị trí, cần review trước khi coi là một JD. |
| **Tổng** | **9.868** | **5.418** | **4.443** | **7** | |

Hai nguồn `data_job_analysis` và `awesome_jobs_vietnam` chiếm **4.261/4.443**, khoảng **95,90%** nhóm needs review. Điều này chủ yếu do quy tắc thận trọng theo loại văn bản, không có nghĩa 4.261 record chắc chắn sai hoặc không dùng được.

Đối với `careersgovsg`, 181 record cần review gồm 143 record có description ngắn và 38 record chỉ có requirements; 4 record không có nội dung hữu ích theo các trường được kiểm tra. Các cờ có thể xuất hiện đồng thời trong các nguồn khác, nên không cộng tất cả số cờ để suy ra số record khác nhau.

## 4. Missing data và nguồn không cung cấp trường

Báo cáo phân biệt các tình huống thay vì gộp mọi giá trị thành null:

- `not_provided`: không có field nguồn nào được mapping đến trường đó; đây là giới hạn schema của nguồn.
- `missing`: có mapping, nhưng key nguồn vắng mặt trong record.
- `null`: key nguồn tồn tại và có giá trị null.
- `empty`: chuỗi rỗng/toàn khoảng trắng, mảng hoặc object rỗng.
- `sentinel`: literal như `nan`, `null`, `n/a`, `na`, `none` hoặc các marker được cấu hình; đếm riêng.
- `unified_null`: kết quả ở staging là null; có thể do nguồn thiếu, rỗng hoặc chuyển kiểu thất bại.

Tỷ lệ `missing/null/empty` dùng mẫu số là số record **có trường được nguồn cung cấp theo mapping**, không tính `not_provided` vào mẫu số đó. Khi nhiều field nguồn cùng ánh xạ vào một trường, báo cáo chọn trạng thái theo thứ tự `present → sentinel → empty → null`; các cờ từng field vẫn được giữ riêng.

Một số kết quả đáng chú ý:

| Nguồn / trường | Quan sát | Diễn giải |
|---|---|---|
| `careersgovsg.description` | 42/2.078 empty | Khoảng 2,02%; không phải nguồn thiếu toàn bộ trường. |
| `careersgovsg.requirements` | 282/2.078 empty | Khoảng 13,57%; không tự đánh dấu JD unusable. |
| `data_job_analysis.description_transformed` | 3/3.187 sentinel | `JD_Trans` chỉ được giữ là văn bản đã biến đổi. |
| `awesome_jobs_vietnam.description` | 1.077/1.077 not provided | Nội dung ở `raw_job_text`; không tự biến issue body thành description. |
| `dpl_evaluation.description` | 395/395 not provided | Có `raw_job_text` và requirements riêng; không tự suy description từ raw text. |
| `it_job_posting.requirements` | 3.101/3.101 not provided | Description vẫn có thể chứa nội dung yêu cầu, nhưng chưa tách section. |

## 5. Phân tích 645 lỗi chuyển kiểu

Báo cáo bước 2 ghi 645 giá trị không chuyển kiểu an toàn; bước 3 đã đối chiếu lại với raw và `source_extra`:

| Nguồn / field | Số giá trị | Nguyên nhân | Cách giữ dữ liệu |
|---|---:|---|---|
| `data_job_analysis.Min_YOE` | 620 | Literal `NA` không phải số năm hợp lệ. | Trường số chuẩn là null; giá trị `NA` gốc nằm trong `source_extra`, kèm cờ sentinel. |
| `ady201m.crawled_at` | 25 | Timestamp dạng ngày–giờ không có múi giờ. | Trường datetime chuẩn là null; chuỗi gốc nằm trong `source_extra`, kèm cờ thiếu timezone. |
| **Tổng** | **645** | | |

Không tự suy 620 giá trị thành số năm kinh nghiệm, không tự gán múi giờ cho 25 timestamp. Đây là số **giá trị**, không phải số record bị loại; mọi record vẫn được bảo toàn.

Các cờ khác gồm `city` là sentinel ở 134 record `it_job_posting`, `Est_Salary` là sentinel ở 146 record `data_job_analysis`, và 5 issue có raw text ngắn. Một record có thể có nhiều cờ.

## 6. Đối soát, kiểm thử và giới hạn

- Xác minh schema/kiểu Parquet, ID, provenance và raw locator theo snapshot được ghi trong mapping report; checksum staging và snapshot được kiểm tra trong quá trình chạy.
- Mỗi dòng quality flags giữ `record_id`, source, file, snapshot SHA-256, locator, status và danh sách cờ.
- Các kiểm thử bước preparation cùng test M01 liên quan: **13/13 pass**. Preflight offline của corpus Gemini `roles_v8` vẫn xác nhận **9.558 unique và 5.915 candidates**; kiểm tra đó không chứng minh chất lượng nhãn Gemini.
- Các số lượng trong báo cáo là raw records; chưa cleaning, dedup hay lọc theo quốc gia/role. Không cộng trực tiếp với số JD unique trong báo cáo Gemini.
- `usable` không phải `EDA_READY`, không phải nhãn gold, và không chứng minh quyền sử dụng dữ liệu hoặc tính đại diện thị trường. Chưa kiểm tra thủ công toàn bộ nội dung, chưa xử lý thông tin liên hệ và chưa xác minh đầy đủ duplicate.

## 7. Đề xuất bước tiếp theo

1. Kiểm tra mẫu phân tầng từ 4.443 record needs review, đặc biệt `JD_Trans` và GitHub Issues; xác định nội dung nào đủ dùng cho mục đích phân tích.
2. Thiết kế quy tắc làm sạch và chuẩn hóa missing có version; quyết định riêng cách xử lý `NA` và timestamp thiếu timezone, giữ raw/provenance.
3. Xây dedup và mapping `record_id → jd_id`; đối soát trước/sau và không tự gộp những trường hợp chưa đủ bằng chứng.
4. Nối nhãn Gemini theo corpus/snapshot và phiên bản phù hợp; giữ riêng nhãn đề xuất, unknown và review cho đến khi được kiểm chứng.

## 8. File liên quan và cách tái tạo

- [Validation report](../data/reports/validation_report.json): tổng hợp trạng thái, cờ và định nghĩa.
- [Missing values report](../data/reports/missing_values_report.csv): thống kê theo nguồn và trường.
- [Quality flags](../data/staging/jd_quality_flags.parquet): trạng thái và lý do theo record.
- [Unified schema](UNIFIED_JD_SCHEMA.md): mapping và quy tắc staging.
- [Mã validation](../src/preparation/quality.py): quy tắc thực thi.

Từ thư mục `IT4930`:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.quality
```

Sau khi chạy lại trên snapshot/staging khác, số liệu trong file phân tích này cần được cập nhật theo báo cáo mới.
