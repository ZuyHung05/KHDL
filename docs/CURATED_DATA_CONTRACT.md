# M02 curated data contract — v1

`data/curated/v1/` là bản phát hành bất biến theo quy trình xuất bản. Chương trình không ghi đè phiên bản đã tồn tại: chạy lại chỉ xác minh checksum và đối chiếu đầu vào; thay đổi dữ liệu hoặc logic cần tạo thư mục phiên bản mới. Đây là bất biến theo quy trình, không phải cơ chế chống sửa file ở cấp hệ điều hành. `manifest.sha256` kiểm tra tính toàn vẹn của `manifest.json`; checksum phát hiện thay đổi, không chứng minh chữ ký hay nguồn gốc mật mã.

## Artifact và điều kiện lọc

| File | Đơn vị | Điều kiện |
|---|---|---|
| `master_jds.parquet` | Một đại diện của nhóm dedup_v2 | Toàn bộ 9.427 nhóm, bao gồm mọi eligibility status |
| `strict_eda.parquet` | Nhóm đại diện | `eligibility_status == 'eligible'` (847 nhóm) |
| `skill_candidates.parquet` | Nhóm đại diện | `skill_extractable == true` (2.208 nhóm); không giới hạn Việt Nam hoặc IT |
| `review_pool.parquet` | Nhóm đại diện | `eligibility_status == 'needs_review'` (8.232 nhóm) |
| `duplicate_mapping.parquet` | Một record nguồn | 9.868 record và mapping tới đại diện, `jd_id`, provenance, lý do dedup |
| `quality_report.json` | Báo cáo | Bản báo cáo bất biến của phiên bản này |
| `manifest.json`, `manifest.sha256` | Metadata | Schema Arrow, hash từng artifact, input, báo cáo, snapshot, bộ lọc và phân bố nguồn |

Các view có thể giao nhau. Strict và skill giao 535 nhóm; skill và review giao 1.649; strict và review không giao theo điều kiện hiện tại. Nhóm `not_eligible` vẫn ở master và có thể có trong skill candidates. Không cộng số dòng các view để suy ra tổng master.

## Schema và provenance

Schema Arrow đầy đủ với datatype và nullable được ghi trong `manifest.json`; master và mọi view có cùng schema và metadata. Mỗi nhóm có `record_id` của đại diện, `jd_id` của dedup_v2, `member_count`, `members_json`, `source_id`, `source_file`, `snapshot_sha256`, `source_locator` và các cột gốc/clean/normalized/quality/eligibility. Giá trị null là thiếu hoặc không chuẩn hóa được, không đồng nghĩa với giá trị âm tính. Các cột `v1_*` là kết quả eligibility v1; `domain_status`, `geography_status`, `content_status`, `eligibility_status`, `eligibility_reason_codes`, `eligibility_evidence`, `skill_extractable` là v2. Nội dung và evidence là nhãn theo quy tắc, không phải gold. Quy tắc schema gốc xem `UNIFIED_JD_SCHEMA.md`; quy tắc và giới hạn eligibility xem `DATASET_ELIGIBILITY_V2_RULES.md`.

Để truy vết, join `master_jds.record_id = duplicate_mapping.representative_record_id` và kiểm tra `jd_id`; mapping lưu `record_id` gốc và bộ thông tin nguồn. Đếm theo source của master dựa trên nguồn **đại diện**, không phải số raw từ nguồn đó; dùng mapping khi cần phân bố raw. Không phân rã Issue thành từng vị trí.

## Kiểm tra và tái tạo

Từ thư mục IT4930:

```sh
.venv/bin/python -m src.preparation.publish_curated
.venv/bin/python -m pytest tests/preparation -q
```

Trước xuất bản, chương trình kiểm tra snapshot hiện hành theo `latest.json` và checksum được ghi khi unified, chuỗi checksum của staging/báo cáo, số lượng, provenance từng member, chạy lại hai bộ quy tắc eligibility để so sánh từng record. Artifact tạm được xác minh rồi mới công bố nguyên thư mục. Chạy lại với `--version v2` tạo bản riêng nếu dữ liệu hoặc logic được cập nhật và mọi điều kiện audit đạt; phiên bản `v1` không bị thay đổi. Quy trình deterministic đối với cùng input, code và môi trường Arrow: bytes Parquet có thể khác với phiên bản Arrow hoặc nén khác. Không rerun toàn bộ M01–M02 để kiểm tra tính deterministic của từng bước cũ; kiểm tra lại logic eligibility v1/v2 và checksum chuỗi hiện tại.

`data/reports/final_quality_report.json` là bản tiện dụng có thể thay đổi khi xuất bản phiên bản khác; dùng `v1/quality_report.json` và manifest khi cần kết quả gắn cố định với v1.

## Reconciliation Gemini cho downstream

Không join theo `jd_id` legacy, không coi Gemini là ground truth. Với từng dự đoán `roles_v8`, đối chiếu **từng thành viên** theo source ID, source file, snapshot SHA và locator, sau đó đối chiếu input thực sự đã gửi (kể cả redaction/truncation), content hash và phiên bản model/prompt/taxonomy. Xây bảng quan hệ legacy ↔ M02, nhận diện một-nhiều/nhiều-một; so sánh nhãn và evidence của từng dự đoán, chuyển mọi xung đột hoặc dữ liệu không tương đương sang review. Chỉ chuyển nhãn gợi ý khi các kiểm tra này được xác minh; lưu phương pháp và lineage, không ghi đè baseline. Báo cáo dedup có 254 legacy ID trải trên nhiều nhóm M02. Hiện không có reconciliation đủ điều kiện để tự động chuyển nhãn.

## Giới hạn sử dụng

Strict EDA chỉ có hai nguồn và là tập chọn bằng quy tắc, không đại diện thị trường tuyển dụng IT Việt Nam. `country_normalized` null không chứng minh không có địa điểm Việt Nam: geography còn có thể dựa vào location. Thiếu ngày đăng, seniority, geography và các nội dung đầy đủ gây bias; không diễn giải số tin hoặc xu hướng theo thời gian như tổng thị trường. Không dùng trạng thái, source hoặc flag làm nhãn gold; audit mẫu v2 nhỏ và không độc lập.
