# Tình trạng Gemini role classification — 21/11/2026

## Corpus và trạng thái

Corpus `roles_v3` dùng trong lượt thử trước và corpus `roles_v8` chuẩn bị cho lượt sau đều được cố định từ 7 snapshot, đối chiếu checksum và taxonomy. `roles_v8` sửa việc xóa nhầm title bắt đầu bằng Application và lọc thêm tài khoản liên hệ; payload của nó chưa được kiểm tra thủ công để gửi API. Có 9.558 JD duy nhất: 3.643 đã có nhãn rule, 5.752 unknown và 163 needs_review. Tập ứng viên là 5.915; smoke50 và pilot200 không chung input hash. Có 5.890 nhóm input hash; sau khi trừ smoke còn 5.840 nhóm. Mẫu pilot `roles_v8` có đại diện ở mọi tầng còn lại sau smoke; các tầng có tỷ lệ lấy mẫu khác nhau, nên không được ngoại suy metric không trọng số thành chất lượng của toàn bộ corpus. Corpus cũ `roles_v7` còn 3 tầng không được đại diện. Nhãn rule chưa được kiểm toán, nhãn Gemini chỉ là đề xuất.

## Kết quả chạy live ban đầu

- `pilot5_v1`: 2 request phân loại trả HTTP 400 (có dấu hiệu lỗi schema), không có kết quả hợp lệ.
- `pilot5_v2`: 3 request phân loại trả HTTP 504; một JD `FAILED`, bốn JD `PENDING`. Bộ lọc cục bộ đã dừng do hết ngân sách run.
- Ngoài 5 request phân loại, có 3 request kiểm tra metadata model thành công trước các lượt bắt đầu/tiếp tục. Chúng chưa được tính trong ngân sách ban đầu. Không khẳng định Google tính metadata vào cùng quota hay không. Để bảo thủ, 3 request đã được thêm vào bộ đếm cục bộ với thời điểm ước lượng bằng thời điểm request phân loại tiếp theo, và từ nay metadata cũng phải được cấp phát quota.
- Không có usage token cho 5 lỗi; input/output token thực tế là **chưa biết**, không phải 0. Chi phí ước tính để trống vì chưa xác minh giá áp dụng riêng cho model; đây không phải dữ liệu billing thực tế. Mức sử dụng từ các công cụ/project khác không thể truy xuất bằng bộ đếm cục bộ.
- Đã dừng gọi API theo yêu cầu. Việc thay đổi model, quota hoặc chạy thêm phải theo chỉ dẫn của người dùng.

## Phần đã triển khai

Có chuẩn hóa/lọc payload, schema Pydantic và xác minh evidence, corpus có provenance và checksum, mẫu smoke/pilot độc lập, cấu hình model/quota, client SDK, quota nội bộ, cache/SQLite, khóa tiến trình, checkpoint/resume, xuất review queue, thống kê trước/sau và biểu đồ. Đã bổ sung gate yêu cầu review smoke, gold hai người gán độc lập và kiểm tra điều kiện chất lượng trước full; full còn yêu cầu xác nhận riêng. Cloud được chuyển review khi chưa đủ gold; cache giữ kết quả gốc đã kiểm chứng để áp dụng lại chính sách review theo từng run. Giới hạn retry/sửa schema được giữ khi resume, và lỗi bất ngờ không đánh dấu run hoàn tất.

Báo cáo của lượt v2 ở `data/curated/role_classification/runs/pilot5_v2/reports/`. Coverage trước/sau đều có tổng 9.558; unknown không đổi vì không có prediction hợp lệ. `state.sqlite` là nguồn checkpoint; JSONL/PNG và payload review chứa nội dung dữ liệu cục bộ, không commit.

## Chưa nghiệm thu

- Chưa có kết quả Gemini live hợp lệ; HTTP 504 cần được xử lý hoặc chờ dịch vụ trước khi đánh giá chất lượng thực tế. Không thể kết luận schema mới đã hoàn toàn tương thích chỉ từ timeout.
- Chưa kiểm tra thủ công đủ 50 kết quả smoke, chưa chạy pilot200, chưa có gold độc lập và chưa có metrics chất lượng thực tế. Hai người gán nhãn phải thực hiện độc lập; không suy gold từ Gemini.
- Chưa chạy full, theo chỉ dẫn của người dùng; không có căn cứ nói Unknown đã giảm.
- Model alias có thể thay đổi bên trong dù tên version không đổi. Bộ lọc thông tin liên hệ không bảo đảm ẩn danh. Crash sau khi API trả response trước khi commit có thể tạo request lặp.
- Các bản run đã đóng băng code/config; sau khi code thay đổi, resume bản cũ có thể bị từ chối và cần tạo run mới. Ngân sách cũ không tự tăng khi resume. Không chạy lại tự động.

## Kiểm thử

Chạy từ `IT4930`:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m src.classification.runner preflight --corpus roles_v8 --dry-run
.venv/bin/python -m src.classification.runner report --run-id pilot5_v2
```

Kết quả gần nhất: 36 test đạt; preflight xác minh 7 snapshot và các tệp corpus. Test mock không chứng minh model live hoạt động hay chất lượng dự đoán. JD không có response hợp lệ được tính là unresolved, không được tính như dự đoán unknown; phản chứng Cloud chỉ đạt nếu có kết quả được kiểm chứng trên JD thực sự nhắc nhà cung cấp cloud.

Có thể đánh giá phản chứng Cloud độc lập từ một run đã hoàn thành cùng model/corpus; output được đối chiếu checkpoint và mẫu phải tách pilot theo ID và hash. Tính năng này mới được kiểm thử bằng dữ liệu giả lập, chưa có kết quả phản chứng live.

Đánh giá pilot hỗ trợ thêm metric mô tả có trọng số nghịch đảo xác suất cho các nhóm input hash sau smoke; metric này không thay thế ngưỡng gate không trọng số, không phải ước lượng cho toàn bộ JD và chưa có khoảng tin cậy. Chưa có gold để tính metric thực tế.
