# Legacy label reconciliation

`python -m src.pipeline reconcile --execute` đối chiếu `roles_v8` và `m02_v1`, ghi artifact riêng trong `data/reconciliation`. Không sửa corpus đóng băng, labels legacy, SQLite hoặc checkpoint.

## Quy tắc chuyển

1. Preflight hai corpus, xác minh release manifest và checksum. Dùng mapping record_id → M02 group; nối legacy bằng bộ `(source_id, source_file, snapshot_sha256, row_index)`. Không join trực tiếp hai loại jd_id.
2. Mỗi member phải có đúng một legacy identity. Dự đoán phải tham chiếu provenance của corpus gốc.
3. Chỉ nhận PROPOSED không yêu cầu review. PENDING và legacy không có dự đoán không được chuyển.
4. So sánh hash của **payload đã preprocess/redact**: cả prediction ↔ legacy input và legacy input ↔ target input phải trùng hoàn toàn. Không coi text tương tự là đủ.
5. Model, preprocessing/schema/prompt version, temperature, corpus manifest hash và taxonomy/role-definition/prompt file hashes phải khớp chính sách hiện tại. Model revision phải có và nhất quán trong nhóm.
6. Validate schema, taxonomy/family và quote evidence trên cả payload cũ và payload mới. Các nhãn primary role/family/seniority giữa nhiều legacy IDs phải nhất quán. Chỉ đổi jd_id trong bản sao nhãn đề xuất khi mọi điều kiện đạt.

Kết quả thực tế: 9.427 nhóm có provenance match; 104 transferred, 5.508 pending, 3.815 blocked, 0 conflict, 0 unmatched. Các reason có thể chồng lấn. Không có conflict thực tế không đồng nghĩa nhánh này chưa được kiểm thử: unit test tạo nhiều legacy IDs có nhãn xung đột và kiểm tra bị chặn.

## Artifact và downstream

- `roles_v8_to_m02_v1.jsonl`: toàn bộ nhóm, record IDs, legacy IDs, hash target, versions, status, lý do và nhãn chuyển nếu có.
- `transferred_predictions.jsonl`: chỉ các đề xuất đã vượt toàn bộ kiểm tra.
- `remaining_candidates.jsonl`: candidates của m02_v1 trừ các nhóm đã chuyển.
- `report.json`: số lượng, reasons và input hashes.

Overlay này chưa tự ghi vào SQLite hay tasks của run live; worker full cũ vẫn đọc frozen candidates của corpus. Downstream cần dùng overlay/remaining queue và duy trì versions tương ứng, hoặc xây importer có kiểm thử trước khi seed một run mới. Không thay tasks của gemini_full_v1. Nhãn chuyển tiếp vẫn không phải gold; việc validate quote chỉ xác nhận bằng chứng tồn tại, không chứng minh suy luận role đúng.
j