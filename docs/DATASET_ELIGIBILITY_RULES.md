# Quy tắc đánh giá eligibility — M02 bước 7

Phiên bản `eligibility_v1` được thực hiện trong `src/preparation/eligibility.py`; SHA-256 của chính file quy tắc được lưu trong metadata Parquet và báo cáo. Đầu vào là đại diện dedup đã normalized; các quyết định là đề xuất để xem xét, không phải ground truth. Không join nhãn Gemini, không lọc hoặc xóa record.

## Ba chiều độc lập

- **Domain:** regex tiêu đề sạch nhận diện một số tên nghề IT rõ ràng (ví dụ software engineer, backend developer) hoặc một số nghề ngoài IT rõ ràng (accountant, teacher). Nếu không khớp hoặc có cả hai bằng chứng thì `unknown`. Từ công nghệ trong mô tả và tên nguồn không tự chứng minh nghề; từ điển hạn chế nên nhiều nghề IT hợp lệ vẫn có thể là `unknown`.
- **Geography:** dùng các giá trị đã được bước normalization nhận diện từ `country`, `city`, `location_raw`: Vietnam hoặc các thành phố Việt Nam trong dictionary là `vietnam`; Singapore, Thailand là `outside_vietnam`. Nhiều vùng xung đột hoặc flag xung đột địa điểm là `unknown`; không nhận diện được là `unknown`. Nguồn CareersGovSG tự nó không chứng minh nơi làm việc; nếu có địa điểm Singapore thực tế thì mới đánh dấu ngoài Việt Nam. Quy tắc không suy từ thông tin cơ quan, quốc tịch hoặc tên repo.
- **Content:** Issue của `awesome_jobs_vietnam` có nội dung là `issue_unstructured`, không giả định một Issue là một vị trí. Nếu chỉ có `description_transformed_clean` thì `transformed_text`. `full_jd` là chỉ báo cấu trúc: mô tả hoặc nhiệm vụ tối thiểu 100 ký tự cùng requirements tối thiểu 40 ký tự, hoặc văn bản tối thiểu 200 ký tự có heading nhiệm vụ và yêu cầu. Đây không bảo đảm chất lượng hay tính đầy đủ thực tế. Nội dung khác là `partial_jd`; thiếu toàn bộ nội dung là `insufficient`. Các trường văn bản luôn giữ riêng và nguyên vẹn.

## Eligibility và truy vết

`eligible` chỉ khi cả ba điều kiện `it`, `vietnam`, `full_jd` cùng đạt. `not_eligible` khi có `non_it`, `outside_vietnam` hoặc `insufficient`; trạng thái này chỉ là kết luận theo quy tắc, record vẫn được lưu. Trường hợp còn lại là `needs_review`. Các cột mới gồm bốn status, `eligibility_reason_codes` và `eligibility_evidence`; evidence lưu trường và đoạn khớp domain, giá trị địa lý chuẩn hóa, hoặc trường và chiều dài nội dung. Các trường gốc, `jd_id`, `members_json`, record ID và provenance không thay đổi. `duplicate_mapping.parquet` tiếp tục liên kết các nhóm với mọi record nguồn.

Trước khi chạy, chương trình đối chiếu SHA-256 của normalized và mapping với báo cáo bước 6, kiểm tra ID duy nhất, số thành viên, `jd_id` và thành viên mapping. Input không khớp sẽ dừng an toàn. Không dùng Gemini API hoặc nhãn Gemini.

Chạy lại từ thư mục dự án:

```sh
.venv/bin/python -m src.preparation.eligibility
.venv/bin/python -m pytest tests/preparation -q
```

Quy tắc cố ý bảo thủ; thống kê không đại diện cho tỉ lệ thực tế của thị trường. Cần đánh giá nhãn thủ công độc lập trước khi sử dụng cho phân tích và đặc biệt trước khi loại bất kỳ nhóm nào.
