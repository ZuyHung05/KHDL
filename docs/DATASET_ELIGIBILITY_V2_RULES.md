# Eligibility v2 — quy tắc và cách chạy

V2 mở rộng `src/preparation/eligibility.py` bằng `src/preparation/eligibility_v2.py`. Đầu vào là bản v1 đã xác thực SHA-256, normalized và mapping đã đối chiếu checksum; kết quả được ghi riêng, giữ bản v1. File Parquet v2 giữ cột v1 dưới tiền tố `v1_`, provenance và các cột gốc. Báo cáo lưu hash input/output, quy tắc, tổng hợp, chuyển trạng thái và reason theo nguồn. `eligibility_v2_audit.json` lưu mẫu thực tế đã xem và inventory Gemini.

- **Domain:** ngoài quy tắc v1, nhận diện một số tên nghề phần mềm cụ thể hoặc nhiệm vụ phát triển/kiểm thử phần mềm với bối cảnh nhiệm vụ (trong `responsibilities` hoặc có dấu hiệu mô tả nhiệm vụ). Một tên công nghệ đơn lẻ không đủ. Dấu hiệu mâu thuẫn nghề non-IT và lập trình được đưa sang unknown. Security/systems engineer đơn thuần mơ hồ; security engineer có thêm bằng chứng cybersecurity được giữ là IT. Các regex và bối cảnh vẫn có thể nhầm; không xem là nhãn vàng.
- **Geography:** kế thừa các giá trị địa điểm chuẩn hóa; thêm bằng chứng từ dòng có nhãn location/nơi làm việc trong JD và tên quốc gia/thành phố thuộc dictionary. Nếu các vùng mâu thuẫn thì unknown. Với GitHub Issues không suy địa điểm từ body vì có thể gồm nhiều vị trí. Không suy quốc gia từ tên nguồn.
- **Content:** giữ nguyên logic và trạng thái v1, kể cả transformed và issue; `insufficient` vẫn được giữ. Điều kiện full JD chỉ là proxy theo heading và độ dài.
- **Skill extractable:** cần ít nhất hai tên công nghệ khác nhau từ dictionary trong trường requirements, transformed, hoặc nội dung có heading skills/requirements; evidence lưu trường và các chuỗi khớp. Đây là cờ ứng viên, không xác nhận kỹ năng thuộc từng vị trí trong Issue hoặc đạt chất lượng trích xuất.
- **Eligibility:** `eligible` chỉ với it + vietnam + full_jd; `not_eligible` nếu non_it, outside_vietnam hoặc insufficient; còn lại needs_review. Mọi status chỉ là nhãn, không loại record. Không dùng Gemini làm ground truth hoặc tự join theo jd_id.

Chạy từ thư mục dự án:

```sh
.venv/bin/python -m src.preparation.eligibility_v2
.venv/bin/python -m src.preparation.eligibility_audit
.venv/bin/python -m pytest tests/preparation -q
```

Thay đổi logic phải thay version và chạy lại audit, cần bộ nhãn độc lập để kiểm chứng trước khi sử dụng để lọc dữ liệu.
