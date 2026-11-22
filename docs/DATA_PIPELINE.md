# Workflow và input/output

| Stage | Input | Output |
|---|---|---|
| ingest | Registry, allowlist, upstream revision | validated checksum-addressed raw snapshots, manifests, latest pointers |
| profile | latest snapshots, explicit adapter mapping | schema_profile.json, schema_mapping.csv |
| unified | snapshots + mapping | unified_jds.parquet, mapping report |
| quality | unified + raw provenance | quality flags, validation report, missing CSV |
| clean | unified + quality | cleaned_jds.parquet, cleaning report |
| dedup | cleaned, identity rules | dedup_v2 representatives, member mapping, cleaning/near QA reports |
| normalize | representatives, rules dictionary | normalized_jds.parquet |
| eligibility / eligibility-v2 | normalized, preceding labels | versioned statuses/evidence, eligibility reports |
| publish | staging + full checksum/provenance audit | immutable versioned master/views/manifest |
| corpus | published master + member provenance | immutable M02 corpus and rule-based candidates |
| gemini | frozen corpus | offline preflight; live classification via explicit classification.runner command |
| reconcile | roles_v8 proposals + m02_v1 inputs | separate validated suggestions and remaining queue |

`src.pipeline` chạy riêng stage (kèm các dependency phía trước), hoặc `all`. `--with-ingest` yêu cầu thêm M01; `--prepare-corpus --corpus ID` bổ sung đóng băng/preflight M03 sau publish. Mặc định không thực thi; `--execute` xác nhận ghi dữ liệu, còn live Gemini không được gọi bởi `all`.

State được ghi atomic sau khi stage subprocess thành công và output/checksum validation đạt. Fingerprint gồm raw bytes, latest pointers, code/config trước đó và output dependency. Input thay đổi trong lúc stage chạy làm stage thất bại. Checkpoint hợp lệ được tái sử dụng, lỗi dừng sớm; khóa pipeline ngăn hai coordinator chạy đồng thời. Có JSONL events trong logs/pipeline.jsonl. Fingerprint cố ý bảo thủ, không khẳng định tối thiểu hóa mọi lần chạy lại.

Mọi release mới cần version mới. Publish audit kiểm tra toàn chuỗi, count, schema metadata, member mapping và chạy lại eligibility. File audit mẫu v2 theo corpus cũ là báo cáo tùy chọn, không phải điều kiện bắt buộc cho một nguồn mới.

Một nguồn mới cần registry, allowlist và explicit field mapping. Fixture integration chạy trong workspace tạm, mock transport, dùng cùng modules production. Nó kiểm tra publish lần đầu, cache/rerun, snapshot mới/release mới giữ bản cũ, checksum lỗi fail-fast; test khác kiểm tra schema-required fields bị đổi hoặc nguồn rỗng không được publish.
