# Audit và kết quả Eligibility v2 — M02 bước 7.1

Đầu vào gồm 9.427 nhóm và mapping tới 9.868 records; không lọc hoặc xóa. V1 giữ nguyên tại `data/staging/eligible_jds.parquet`; V2 tại `data/staging/eligible_jds_v2.parquet`, có cả các cột `v1_*` để đối chiếu. Không dùng nhãn Gemini và không gọi API.

## Coverage v1 / v2

| Chiều | V1 | V2 |
|---|---|---|
| domain_status | it: 3,508; unknown: 5,902; non_it: 17 | it: 4,161; unknown: 5,251; non_it: 15 |
| geography_status | vietnam: 5,788; outside_vietnam: 326; unknown: 3,313 | vietnam: 5,789; outside_vietnam: 327; unknown: 3,311 |
| content_status | transformed_text: 3,184; full_jd: 3,779; partial_jd: 1,380; issue_unstructured: 1,077; insufficient: 7 | transformed_text: 3,184; full_jd: 3,779; partial_jd: 1,380; issue_unstructured: 1,077; insufficient: 7 |
| eligibility_status | needs_review: 8,473; not_eligible: 349; eligible: 605 | needs_review: 8,232; not_eligible: 348; eligible: 847 |

`skill_extractable=true`: 2,208 nhóm. Đây là cờ khả năng trích xuất theo quy tắc, không xác nhận kỹ năng, không bảo đảm đầy đủ và không hàm ý eligibility.

## Eligibility theo nguồn

| Nguồn | V1 eligible / review / not eligible | V2 eligible / review / not eligible |
|---|---:|---:|
| data_job_analysis | 0 / 3125 / 62 | 0 / 3125 / 62 |
| careersgovsg | 0 / 1800 / 278 | 0 / 1799 / 279 |
| it_job_posting | 513 / 2142 / 5 | 713 / 1944 / 3 |
| awesome_jobs_vietnam | 0 / 1077 / 0 | 0 / 1077 / 0 |
| dpl_evaluation | 92 / 303 / 0 | 134 / 261 / 0 |
| ady201m | 0 / 21 / 4 | 0 / 21 / 4 |
| vietjobs | 0 / 5 / 0 | 0 / 5 / 0 |

## Nguyên nhân còn chưa xác định

Bảng sau đếm unknown theo domain và geography; content không có nhãn unknown: các trạng thái khác full được thể hiện riêng, không suy là thiếu dữ liệu.

| Nguồn | Domain unknown | Geography unknown | Transformed / Issue / Partial / Insufficient |
|---|---:|---:|---:|
| data_job_analysis | 1319 | 281 | 3184 / 0 / 0 / 3 |
| careersgovsg | 1784 | 1806 | 0 / 0 / 37 / 4 |
| it_job_posting | 1254 | 95 | 0 / 0 / 1302 / 0 |
| awesome_jobs_vietnam | 637 | 1077 | 0 / 1077 / 0 / 0 |
| dpl_evaluation | 231 | 27 | 0 / 0 / 41 / 0 |
| ady201m | 21 | 25 | 0 / 0 / 0 / 0 |
| vietjobs | 5 | 0 | 0 / 0 / 0 / 0 |

Các lý do định lượng theo nguồn, chuyển trạng thái từng chiều và từng nguồn có trong `eligibility_v2_report.json`. Unknown domain chủ yếu vì tiêu đề/nhiệm vụ không khớp quy tắc hoặc có xung đột; geography do địa chỉ không nhận diện được, không có trường địa lý hoặc bằng chứng mâu thuẫn. GitHub Issues không được gán địa điểm chỉ từ một đoạn trong body vì có thể chứa nhiều vị trí. `data_job_analysis` chủ yếu là văn bản biến đổi; điều này không chứng minh toàn văn JD.

## Audit mẫu và sai lệch

Mẫu thuận tiện 18 nhóm được người triển khai chọn và đối chiếu thủ công theo nội dung đã xem, bao gồm 7 nguồn và ba trạng thái v1; không ngẫu nhiên, không độc lập và không phải ground truth. Chỉ adjudicate chiều domain; các trường hợp scope chưa rõ ghi unknown. Ma trận sau là số lượng theo nhãn tham chiếu → dự đoán, không phải precision/recall của toàn corpus.

- v1: it -> it: 6; it -> unknown: 3; non_it -> unknown: 4; unknown -> unknown: 1; unknown -> non_it: 2; non_it -> non_it: 2.
- v2: it -> it: 8; non_it -> unknown: 4; unknown -> unknown: 3; it -> unknown: 1; non_it -> non_it: 2.

Hai trường hợp v1 bỏ sót bằng chứng nghề IT là AI Engineer và DWH/BI Developer; v2 nhận diện được. V1 gán hai giáo viên dạy lập trình là non-IT, nhưng phạm vi nghiên cứu có thể bao gồm đào tạo IT, nên v2 đưa sang unknown. Embedded Systems Engineer có nhiệm vụ lập trình cụ thể nhưng v2 vẫn unknown: đây là một trường hợp bỏ sót còn lại, được giữ để tránh mặc định mọi systems engineer là IT. Một số công việc ngoài IT như quản lý công viên, tư vấn an toàn thực phẩm vẫn unknown, vì chưa bổ sung từ điển không đủ kiểm chứng. Các ví dụ trong `eligibility_v2_audit.json` có record ID, tiêu đề, nhãn và lý do.

## Đối chiếu Gemini roles_v8

File predictions có trạng thái PROPOSED/REVIEW_REQUIRED/PENDING; PENDING không phải kết quả dự đoán. Báo cáo dedup trước đó ghi 254 legacy ID bị tách thành nhiều nhóm. Chưa có đối chiếu đầy đủ từng thành viên provenance, payload sau biến đổi và xung đột nhãn; vì vậy không chuyển nhãn sang v2. Thống kê inventory tại thời điểm audit có trong file audit và có thể thay đổi nếu Gemini đang chạy.

## Giới hạn

Đánh giá này dựa vào các quy tắc và mẫu nhỏ; `eligible` không là nhãn vàng. False positive vẫn có thể phát sinh khi title hoặc ngữ cảnh duty bị hiểu sai, địa điểm trong JD không phải địa điểm làm việc, hoặc heading bị nhận diện nhầm. Cần bộ nhãn độc lập đủ lớn và review có hệ thống trước khi dùng làm căn cứ lọc/phát hành tập cuối.
