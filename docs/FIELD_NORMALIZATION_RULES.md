# Field Normalization — quy tắc `field_normalization_v1`

## Phạm vi

Chạy trên `data/staging/deduplicated_jds.parquet`, kiểm tra mỗi `jd_id` có đúng một representative và danh sách thành viên khớp `duplicate_mapping.parquet`. Input hiện tại: 9.427 nhóm và 9.868 record nguồn. Output giữ nguyên mọi cột đầu vào và thêm cột normalized, status, flags và evidence. Raw, cleaning, dedup và Gemini không bị ghi lại.

Dictionary và version nằm trong `configs/field_normalization.yaml`. SHA-256 dictionary, input dedup và mapping được lưu trong metadata Parquet và báo cáo. Mọi quy tắc là quy tắc có thể kiểm tra, không phải nhãn gold; thay dictionary cần tăng version và chạy lại.

## Cột và quy tắc

| Cột | Kiểu | Quy tắc |
|---|---|---|
| `location_normalized` | list<string> / null | Chỉ nhận các địa danh có alias trong dictionary từ `city` và `location_raw`. Có thể trả nhiều địa danh; nếu city và location cùng nhận diện nhưng mâu thuẫn thì null và gắn `location_conflict`. Không suy địa danh từ tên công ty hay JD. |
| `country_normalized` | list<string> / null | Chỉ nhận khi `country` hoặc toàn bộ `location_raw` khớp chính xác tên/alias quốc gia trong dictionary. Không suy quốc gia từ thành phố, domain hoặc nguồn. |
| `experience_years_min_normalized`, `experience_years_max_normalized` | float64 / null | Dùng trường số minh thị 0–60. Không trích số năm từ title/JD hoặc suy từ seniority. Nếu min > max, bỏ cả hai giá trị normalized và gắn flag. Với Careers@Gov, không dùng giá trị số khi `experience_raw` không có nội dung; cặp 0–0 được giữ null vì có thể là giá trị mặc định không rõ nghĩa. |
| `seniority_normalized` | string / null | Chỉ map `seniority_source` khi trùng chính xác một alias. Nhiều cấp hoặc giá trị không nhận diện → null và flag; không dùng mã `L1…L4`, không suy từ title hoặc số năm. Giá trị từ nguồn có thể là nhãn nguồn suy luận, không phải gold. |
| `employment_type_normalized` | list<string> / null | Map exact alias, bao gồm `permanent/contract` và `contract / freelance` là nhiều giá trị. Với `data_job_analysis`, đọc thêm `W_Term_2..4` trong `source_extra`; alias là work arrangement được xét ở trường đó. Nhiều employment values gắn `employment_multiple`. |
| `work_arrangement_normalized` | string / null | Chỉ map alias rõ ràng remote/hybrid/on-site từ `work_arrangement`, location chỉ khi toàn bộ là alias, cờ remote = 1 hoặc W_Term bổ sung rõ ràng. Remote flag = 0 không suy ra on-site. Giá trị xung đột → null và flag. `Full-time`/`Part-time` là schedule, không phải arrangement. |
| `posted_at_normalized` | timestamp UTC / null | Chỉ sao chép `posted_at` đã có timezone. Không dùng ngày crawl, issue created hay thời điểm tải thay thế; không gán timezone cho datetime naive. |

`normalization_evidence` là JSON object lưu các trường nguồn đã được dùng, không chứa key API. `normalization_status`: `normalized` nếu có ít nhất một trường chuẩn hóa và không có flag; `needs_review` nếu có flag (các trường khác vẫn có thể có giá trị); `no_evidence` khi không có giá trị chuẩn hóa và không có flag. Không suy rằng `normalized` nghĩa là mọi trường đầy đủ hoặc đúng về ngữ nghĩa.

Giá trị null/empty và sentinel toàn giá trị `NA`, `N/A`, `nan`, `null`, `none`, `not specified`, `not applicable`, `unknown`, `không rõ` được xem là thiếu **khi so khớp**, không sửa input. Tên technology và nội dung JD không tham gia normalization. Những giá trị không nhận diện/đa nghĩa được để null hoặc map phần chắc chắn và gắn flag; mã nguồn chưa rõ không được diễn giải.

## Coverage và giới hạn

`normalization_report.json` ghi số record, số field đầu vào không rỗng, số normalized, unknown và tỷ lệ theo từng nguồn/cột, cùng số flag. `input_nonempty` biểu diễn **có một trong các trường đầu vào liên quan**, không nhất thiết là bằng chứng đủ cho field đích; ví dụ `location_raw` có thể chứa thành phố nhưng không chứa quốc gia, `source_remote_flag=0` không chứng minh on-site. Vì vậy không dùng `input_nonempty` làm ground truth hoặc gọi chênh lệch coverage là độ chính xác.

Danh mục địa danh nhỏ, chưa bao phủ mọi tỉnh/thành, quốc gia và địa chỉ; trường còn lại để review, không tự gán. Việc phát hiện alias địa danh trong chuỗi địa chỉ là sơ bộ, và location nhiều nơi vẫn giữ danh sách. Cột `needs_review` có thể chiếm nhiều dòng vì một flag nhỏ ở bất kỳ trường nào; không loại record hoặc thay đổi nhãn chất lượng bước 3. Kết quả không phải curated cuối.

## Cách chạy

Từ thư mục `IT4930` với Python môi trường dự án:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m src.preparation.normalize
```

Kết quả: `data/staging/normalized_jds.parquet`, `data/reports/normalization_report.json`. Lệnh không gọi API và không cập nhật Gemini.
