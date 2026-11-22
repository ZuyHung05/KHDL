# Phân tích kết quả bước 7 — Dataset Eligibility Assessment

Theo `data/reports/eligibility_report.json`, đầu vào và đầu ra đều có **9.427 nhóm**, mapping tới **9.868 record nguồn**. Không record nào bị loại. Đây là đánh giá theo quy tắc `eligibility_v1`, không phải nhãn xác thực thủ công.

| Chiều | Phân bố số nhóm |
|---|---|
| Lĩnh vực | IT 3.508; non-IT 17; unknown 5.902 |
| Địa lý | Việt Nam 5.788; ngoài Việt Nam 326; unknown 3.313 |
| Nội dung | full JD 3.779; partial 1.380; transformed 3.184; issue unstructured 1.077; insufficient 7 |
| Eligibility | eligible 605; needs review 8.473; not eligible 349 |

| Nguồn đại diện | Eligible | Needs review | Not eligible |
|---|---:|---:|---:|
| data_job_analysis | 0 | 3.125 | 62 |
| careersgovsg | 0 | 1.800 | 278 |
| it_job_posting | 513 | 2.142 | 5 |
| awesome_jobs_vietnam | 0 | 1.077 | 0 |
| dpl_evaluation | 92 | 303 | 0 |
| ady201m | 0 | 21 | 4 |
| vietjobs | 0 | 5 | 0 |

Số `unknown` về lĩnh vực cao vì chỉ một tập tên nghề rõ ràng được nhận diện; không thể suy rằng các nhóm này không phải IT. `data_job_analysis` phần lớn chỉ có văn bản biến đổi, nên không được tự coi là full JD. Toàn bộ 1.077 Issue được giữ riêng vì có thể chứa nhiều vị trí. Với CareersGovSG, 271 nhóm có địa điểm ngoài Việt Nam được nhận diện, còn 1.807 nhóm thiếu bằng chứng địa lý đủ rõ; tên nguồn không được dùng để kết luận địa điểm.

605 nhóm `eligible` chỉ đáp ứng ngưỡng cấu trúc và quy tắc hiện tại; cần kiểm chứng thủ công, đặc biệt heading và nội dung có thể gây nhận diện nhầm. Tương tự, `not_eligible` không đồng nghĩa record bị xóa hoặc là kết luận cuối cùng. Không so sánh trực tiếp số nhóm theo nguồn với số raw trước dedup vì một nhóm có thể có nhiều thành viên. Chi tiết và checksum nằm trong báo cáo JSON; lý do/evidence theo từng nhóm nằm trong Parquet. Quy tắc tại `docs/DATASET_ELIGIBILITY_RULES.md`.
