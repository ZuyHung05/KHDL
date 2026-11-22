# Phân tích kết quả M02 bước 8

Bản curated v1 giữ đủ **9.427 nhóm đại diện** và mapping tới **9.868 record nguồn**. Chuỗi checksum của snapshot đầu vào và các artifact staging khớp báo cáo tương ứng; provenance từng record được đối chiếu. Hai bộ quy tắc eligibility được tính lại trên từng nhóm và cho cùng kết quả. Việc kiểm tra không chạy lại toàn bộ các bước M01–M02 trước đó, nên không khẳng định tính tái lập end-to-end cho mọi phiên bản môi trường.

| Tập | Số nhóm | Phân bố theo nguồn |
|---|---:|---|
| Master | 9.427 | data_job_analysis 3.187; careersgovsg 2.078; it_job_posting 2.660; awesome_jobs_vietnam 1.077; dpl_evaluation 395; ady201m 25; vietjobs 5 |
| Strict EDA | 847 | it_job_posting 713; dpl_evaluation 134 |
| Skill candidates | 2.208 | it_job_posting 1.017; awesome_jobs_vietnam 492; data_job_analysis 274; dpl_evaluation 166; careersgovsg 259 |
| Review pool | 8.232 | data_job_analysis 3.125; careersgovsg 1.799; it_job_posting 1.944; awesome_jobs_vietnam 1.077; dpl_evaluation 261; ady201m 21; vietjobs 5 |

Strict giao skill 535 nhóm; skill giao review 1.649. Các tập không loại trừ nhau. Strict chỉ có hai nguồn, vì vậy phân tích thị trường từ tập này chịu selection bias rõ rệt.

Ở cấp nhóm đại diện, `country_normalized` thiếu/rỗng 9.056 (96,1%), `location_normalized` 3.402 (36,1%), `seniority_normalized` 9.059 (96,1%) và `posted_at_normalized` 7.349 (78,0%). Country thiếu không đồng nghĩa geography unknown: v2 còn xét location; thực tế geography unknown là 3.311. `requirements_clean` thiếu/rỗng 7.206 (76,4%), nhưng yêu cầu có thể nằm trong mô tả hoặc văn bản khác. Thống kê này gộp null và empty ở cấp đại diện; phân biệt missing, null, empty và field không được nguồn cung cấp trong báo cáo bước 3.

Dedup xác nhận 441 nhóm trùng và gộp 441 record, còn 29 near-duplicate candidates cần xem xét. Cleaning QA ban đầu gắn cờ 50 record giảm nhiều; audit 22 trường hợp chưa đối chiếu được không phát hiện mất token được chọn, nhưng so khớp token không đảm bảo bảo toàn ngữ nghĩa. Chất lượng và nhãn chưa được xác nhận bởi bộ ground truth độc lập.

Bản v1 và checksum xem `data/curated/v1/manifest.json`; thống kê chi tiết, coverage normalization, số liệu nguồn và cảnh báo nằm trong `data/curated/v1/quality_report.json`. Hướng dẫn dùng và reconciliation Gemini nằm trong `docs/CURATED_DATA_CONTRACT.md`.
