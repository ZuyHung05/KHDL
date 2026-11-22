# Đề xuất Unified JD Schema

## Phạm vi và phương pháp

Khảo sát 7 nguồn có `data/raw/<source_id>/latest.json`, đọc từng file mà con trỏ chỉ tới và xác minh SHA-256. Tổng cộng **9.868 raw records**; đây là số dòng nguồn, chưa dedup và không mặc định là 9.868 việc làm riêng biệt. Hai thư mục legacy `it_job_posting/main` và commit SHA không được quét vì không phải snapshot do `latest.json` chỉ định.

Chi tiết từng field, kiểu quan sát và tỷ lệ thiếu nằm trong `data/reports/schema_profile.json`; ánh xạ từng field nằm trong `data/reports/schema_mapping.csv`. Profile có danh sách snapshot và checksum để tái lập. Nếu sau này có thư mục nguồn không có latest pointer thì không được tự chọn phiên bản mới nhất theo thời gian file; cần bổ sung pointer hoặc báo nguồn chưa có snapshot hiện hành.

- **Missing**: key không tồn tại trong record. **Null**: giá trị JSON null. **Empty**: chuỗi rỗng/toàn whitespace hoặc mảng/object rỗng. Ba loại này tách nhau; tỷ lệ tính trên tổng record của file.
- Chuỗi `nan`, `null`, `none`, `n/a`, `na` được thống kê riêng là `sentinel_literal`; chúng vẫn là chuỗi nguồn và không bị tự động chuyển thành null. Mọi giá trị CSV được đọc là string, kể cả số và boolean; kiểu trong schema bên dưới là **đề xuất**, chưa ép kiểu.
- Độ dài tính theo Unicode codepoints của từng chuỗi không rỗng, có min, mean, median, p90 và max. Trường mảng được ghi `nonstring_text_count`, không giả định độ dài mảng là độ dài description. Không làm sạch, gộp hay thay đổi raw.

## Schema đề xuất

Các cột required là điều kiện cho **bản ghi chuẩn hóa tương lai**, không phải khẳng định mọi nguồn đã đáp ứng. Một nguồn có raw JD text nhưng không tách được description được giữ raw_job_text và không tự suy description.

| Trường | Kiểu đề xuất | Bắt buộc | Ý nghĩa |
|---|---|---|---|
| `record_id` | string | Có | ID nội bộ xác định record nguồn; được tạo khi chuẩn hóa, không có sẵn ở mọi nguồn. |
| `source_id`, `source_file`, `snapshot_sha256`, `source_locator` | string | Có | Nguồn, file, checksum, vị trí dòng/issue để truy về raw. |
| `job_title` | string | Có | Tên việc làm như nguồn cung cấp; giữ nguyên `title_raw` trong provenance nếu chuẩn hóa. |
| `description`, `requirements`, `responsibilities` | string hoặc null | Không | Nội dung các phần tương ứng khi nguồn tách rõ. |
| `raw_job_text` | string hoặc null | Không | Toàn bộ văn bản JD/issue; có thể gộp title, yêu cầu và liên hệ, không tương đương description. |
| `description_transformed` | string hoặc null | Không | Văn bản đã dịch/biến đổi của nguồn, không khẳng định là bản gốc. |
| `preferred_requirements`, `education_requirements`, `language_requirements`, `certification_requirements`, `portfolio_requirements`, `behavioral_traits`, `benefits` | string, array hoặc null | Không | Nội dung/nhãn theo nguồn; giữ kiểu nguồn đến khi xác định chuyển đổi có kiểm chứng. |
| `source_job_id`, `source_posting_id`, `source_url`, `platform`, `source_status` | string hoặc null | Không | Định danh tại nguồn và trạng thái. Careers@Gov cần tổ hợp platform + jobId + postingNo. |
| `company_name`, `company_source_id`, `company_image_url`, `company_description` | string hoặc null | Không | Thông tin nhà tuyển dụng/cơ quan. |
| `location_raw`, `city`, `country`, `work_arrangement` | string hoặc null | Không | Địa điểm/remote như nguồn; không tự suy quốc gia hay thành phố. |
| `employment_type`, `employment_type_code`, `working_hours` | string hoặc null | Không | Loại và thời gian làm việc. Nguồn có nhiều `W_Term` cần giữ danh sách. |
| `experience_raw` | string, object hoặc null | Không | Kinh nghiệm theo nguồn; object của dpl_evaluation giữ nguyên cấu trúc. |
| `experience_years_min`, `experience_years_max` | number hoặc null | Không | Số năm khi nguồn cung cấp rõ; CSV cần chuyển kiểu có kiểm chứng. |
| `seniority_source`, `source_level_fields` | string, object hoặc null | Không | Level/giá trị L1–L4 gốc; không tự hiểu các mã chưa có tài liệu. |
| `salary_raw`, `salary_min`, `salary_max`, `salary_average`, `salary_estimate` | string hoặc number hoặc null | Không | Lương gốc, các giá trị nguồn và ước tính; đơn vị/currency/chu kỳ phải xác minh trước khi so sánh. |
| `source_skill_labels`, `source_role_label`, `source_role_family`, `source_role_flags` | string, array hoặc object hoặc null | Không | Nhãn có sẵn hoặc suy luận từ nguồn; không coi là ground truth. |
| `industry`, `source_category`, `source_category_code`, `functional_area`, `functional_area_code`, `education_code` | string hoặc null | Không | Phân loại và mã do nguồn cung cấp; các field cùng đích cần giữ provenance và quy tắc ưu tiên khi triển khai. |
| `posted_at`, `closing_at`, `source_created_at`, `source_updated_at`, `source_closed_at`, `source_crawled_at` | datetime hoặc null | Không | Các thời điểm riêng biệt; timestamp Careers@Gov là epoch milliseconds, ngày scrape không phải ngày đăng. |
| `closing_date_text`, `source_remaining_days`, `source_new_flag`, `source_vietnam_flag`, `source_remote_flag` | string/boolean hoặc null | Không | Trạng thái hiển thị hoặc cờ nguồn, không suy diễn khi thiếu. |
| `application_instructions` | string hoặc null | Không | Hướng dẫn ứng tuyển nguồn; có thể chứa thông tin liên hệ. |
| `source_extra` | object | Không | Giữ mọi field nguồn chưa hiểu hoặc chưa mapping; không loại bỏ thông tin. |

Trường `source_*` bảo toàn ngữ nghĩa gốc. Khi nhiều field nguồn ánh xạ về cùng đích, mapping CSV thể hiện quan hệ nhiều-một; không tự nối hoặc ghi đè trước khi có quy tắc đã kiểm chứng.

## So sánh các snapshot

| Nguồn | Records | Description / raw JD text | Requirements |
|---|---:|---|---|
| it_job_posting | 3.101 | `description`: 3.101 chuỗi có nội dung; median 2.431 ký tự | Không có field riêng |
| dpl_evaluation | 395 | `raw job`: 395 chuỗi; median 1.305 | `must_have_requirements` là mảng; `preferred_requirements` rỗng 336 dòng |
| vietjobs | 5 | `description`: 5 chuỗi; median 492 | `requirements_text`: 5 chuỗi; median 322 |
| data_job_analysis | 3.187 | `JD_Trans`: 3.184 chuỗi có nội dung thông thường; 3 sentinel; median 103 | Không có field riêng |
| careersgovsg | 2.078 | `jobDescription`: 42 rỗng, 2.036 chuỗi; median 574 | `jobRequirements`: 282 rỗng, 1.796 chuỗi; median 934 |
| ady201m | 25 | `Mô tả công việc`: 25 chuỗi; median 524 | `Yêu cầu ứng viên`: 25 chuỗi; median 398 |
| awesome_jobs_vietnam | 1.077 | `body`: 1.077 chuỗi Markdown issue; median 2.150 | Nội dung có thể nằm trong body, không có field riêng |

Median chỉ tính chuỗi có nội dung, không tính sentinel; không phản ánh chất lượng hay độ đầy đủ của JD.

## Những vấn đề cần xử lý trước khi chuẩn hóa

1. Một issue GitHub có thể mô tả nhiều vị trí, trùng nội dung ở URL khác hoặc có thông tin liên hệ. `record_id` ở đây đại diện issue nguồn, không chứng minh số việc làm unique.
2. ADY201m có nội dung nhiều ngành; Careers@Gov là Singapore và VietJobs là mẫu năm dòng nhiều ngành. Không suy ra toàn bộ tập là IT Việt Nam.
3. `JD_Trans` là nội dung đã biến đổi và nhiều dòng rất ngắn; không gọi là full JD. `raw job` của dpl_evaluation chứa văn bản kết hợp, không tách section khi chưa có bằng chứng.
4. Mảng requirements và các chuỗi biểu diễn danh sách trong CSV khác kiểu. Không dùng `eval`; nếu chuẩn hóa, cần parser an toàn và ghi lỗi riêng.
5. Các cột role và skills trong nguồn có thể đã được suy luận hoặc làm sạch; bảo toàn nhãn nguồn, không dùng làm ground truth.
6. Việc thiếu URL/company khiến so khớp giữa nguồn không chắc chắn. `jobId` ở Careers@Gov có ý nghĩa phụ thuộc platform; cần ID tổng hợp theo tài liệu nguồn.
7. Profile không kiểm tra bản quyền, chất lượng ngữ nghĩa của mọi ô hoặc tính mới của tin. Cần xem license/provenance trước khi tái sử dụng, và kiểm tra privacy trước khi chia sẻ.

## Tái tạo báo cáo

Chạy từ thư mục `IT4930`:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m scripts.profile_raw_schema
```

Lệnh đọc snapshot raw và ghi lại hai báo cáo schema; không cập nhật latest hay thay đổi dữ liệu raw.

## Triển khai staging bước 2

Chạy từ thư mục `IT4930` sau khi cài `requirements-preparation.txt`:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.unified
```

Kết quả là `data/staging/unified_jds.parquet` và `data/reports/unified_mapping_report.json`. Đầu vào lấy từ registry và `latest.json`, kiểm tra checksum trước và sau khi đọc. `source_locator` là JSON có `row_index` bắt đầu từ 0; issue GitHub thêm `issue_number`. `record_id` là SHA-256 của source, file, snapshot checksum và locator; do đó ổn định với cùng snapshot và thay đổi khi snapshot thay đổi.

Parquet có schema cố định. Các cột đa kiểu, bao gồm `requirements`, được mã hóa thành **JSON text** để phân biệt chuỗi, mảng và object; đọc bằng `json.loads` sau khi kiểm tra null. Các cột JSON được liệt kê trong parquet schema metadata và báo cáo mapping. `source_extra` là JSON object chứa các trường chưa ánh xạ, trường không được chọn do nhiều nguồn vào cùng đích, và giá trị gốc không chuyển kiểu được. Dùng `json.loads`, không dùng `eval`.

Quy tắc nhiều field về một đích: `W_Term` → `W_Term_2` → `W_Term_3` → `W_Term_4` và `category` → `field`; giá trị đầu tiên có nội dung được chọn, các field còn lại lưu `source_extra`. Các trường `source_skill_labels`, `source_role_flags`, `source_level_fields` lưu JSON object theo tên field gốc, không nhập nhằng hay ghi đè. Nếu xuất hiện nhóm nhiều field chưa có quy tắc, lệnh dừng thay vì tự chọn.

Chuỗi trống đưa về null; các sentinel dạng chữ như `nan` được giữ nguyên trong trường string. Với numeric/datetime không chuyển được, trường chuẩn để null, tăng bộ đếm conversion error và bảo toàn giá trị gốc ở `source_extra`. Không tự suy múi giờ cho timestamp thiếu timezone, không suy nguồn location, role hoặc salary. Không chuyển `raw_job_text` thành `description`.

## Structural validation và quality flags — bước 3

Từ thư mục `IT4930`, chạy:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.quality
```

Lệnh kiểm tra checksum Parquet theo mapping report, schema/kiểu, ID và locator, rồi đối chiếu từng dòng với raw snapshot được ghi trong report bước 2. Kết quả gồm `data/staging/jd_quality_flags.parquet`, `data/reports/validation_report.json` và `data/reports/missing_values_report.csv`; không cập nhật raw hoặc nhãn Gemini.

Nhãn chất lượng dựa trên quy tắc cơ học: `usable` cần title và description từ 100 ký tự hoặc raw JD text từ 100 ký tự (trừ GitHub issue body); `needs_review` gồm title thiếu/sai, lỗi cấu trúc, nội dung ngắn, chỉ có requirements, chỉ có description đã biến đổi, hoặc issue body có thể chứa nhiều vị trí; `unusable` là không có nội dung hữu ích ở description, requirements, raw job text và description_transformed. Có cấu trúc lỗi nhưng không có nội dung vẫn là unusable. Ngưỡng 100 ký tự là heuristic, không chứng minh JD đầy đủ và không đánh giá nghề IT.

CSV missing phân biệt `not_provided` (không có field nguồn tương ứng theo mapping), `missing` (có mapping nhưng key vắng mặt trong record), `null`, `empty`, `sentinel`, `present`. Khi nhiều field nguồn ánh xạ cùng một trường, phân loại theo thứ tự `present`, `sentinel`, `empty`, `null`; denominator cho phần trăm thiếu là số record có field được nguồn cung cấp theo mapping. `unified_null` là trạng thái staging sau mapping, nên có thể khác trạng thái raw, ví dụ lỗi chuyển kiểu.

Trong snapshot hiện tại 645 lỗi chuyển kiểu gồm 620 `Min_YOE` có literal `NA` và 25 `crawled_at` thiếu timezone; giá trị gốc được kiểm tra lại trong `source_extra`, không ép kiểu. Các quality flag là chẩn đoán sơ bộ, không sửa dữ liệu và không phải nhãn Role Classification.

## Text cleaning — bước 4

Chạy từ `IT4930`:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.cleaning
```

Lệnh tạo `data/staging/cleaned_jds.parquet` và `data/reports/cleaning_report.json`; kiểm tra checksum unified staging với validation report và đối soát chính xác ID/provenance của quality flags. Giữ toàn bộ cột gốc, thêm các cột `job_title_clean`, `description_clean`, `requirements_clean`, `raw_job_text_clean`, `description_transformed_clean`, `responsibilities_clean`, `cleaning_version`, `cleaning_flags`, `quality_status` và `quality_flags`. `requirements_clean` vẫn là JSON text cùng cấu trúc chuỗi/mảng/object của input; giải mã bằng `json.loads`. Không tự ghép các trường hoặc điền salary, location, kinh nghiệm hay timezone.

Quy tắc `jd_text_clean_v1` giải mã HTML entities tới trạng thái ổn định, chuẩn hóa NFC, loại ký tự điều khiển, bỏ markup HTML/Markdown nhận biết được, bảo toàn dấu headings/list, đích link và nội dung văn bản. Chỉ xóa dòng boilerplate khớp chính xác `click here to apply`. Chỉ chuyển sentinel toàn giá trị ở `data_job_analysis.description_transformed`, là ngữ cảnh đã xác nhận trong schema profile; không thay thế chuỗi con JD. Các field gốc và raw không thay đổi.

Flag `large_reduction:<field>` xảy ra khi text gốc từ 100 ký tự trở lên và text sau clean còn dưới 50%; đây có thể là markup bị loại, cần đối chiếu chứ không tự kết luận mất nội dung. `technology_marker_reduced:<field>` cho biết số lần xuất hiện của các ký hiệu C++, C#, .NET, Node.js, CI/CD hoặc AWS EC2 giảm; flag chỉ bao phủ danh sách cụ thể này, không bảo đảm kiểm tra hết mọi tên công nghệ. `clean_error` hoặc `content_became_empty` cũng được lưu theo record. Báo cáo thống kê số record thay đổi, số lần chuyển sentinel và flag theo nguồn.
