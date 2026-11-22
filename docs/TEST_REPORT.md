# Verification — priorities 1–3 and GitHub review

## Kết quả

- Full local suite: 94 PASS, 14 matplotlib/pyparsing deprecation warnings.
- Source-only export từ danh sách file không bị Git ignore, chạy từ root export, không .env/data local: 86 PASS, 8 SKIP, 14 warnings.
- `pip check`: No broken requirements found.
- Existing immutable v1 và corpus m02_v1 được kiểm tra lại qua CLI; tất cả M02 stage CACHED, release được xác minh và không ghi đè. Không gọi Gemini API.

## Những nhánh được kiểm thử

- Reconciliation: exact input chuyển được và remap JD ID trên bản sao, input/version khác bị chặn, PENDING/missing/review không chuyển, nhiều legacy IDs nhãn khác nhau bị conflict, evidence không tồn tại bị chặn.
- Nguồn mới: registry + allowlist và schema vacancy_name/duties_text/must_know; ingestion production với transport mock → immutable snapshot/manifest → schema profile → adapter → quality → cleaning → dedup_v2/audit → normalization → eligibility v2 → curated publish.
- Rerun dùng cache; snapshot mới tạo release mới và giữ manifest release cũ. Snapshot checksum lỗi dừng trước khi phát hành. Nguồn rỗng và thiếu required field bị quarantine, không tạo latest pointer.
- CLI stage lỗi không được checkpoint thành công, có FAILED event. Config/output đổi làm cache mất hiệu lực. Integrity/filtering/manifest/provenance/deterministic checks có trong bộ preparation hiện hữu.
- Missing adapter có lỗi chỉ rõ mapping cần bổ sung. Unit/mock Gemini tests hiện hữu kiểm tra schema, retry/quota/cache/resume; live provider không được gọi.

## Reconciliation thực tế

9.427 nhóm provenance-matched; 104 transferred, 5.508 pending, 3.815 blocked, 0 conflict/unmatched. M02 corpus có 5.753 candidates; overlay chuyển được 104 và hàng đợi riêng còn 5.649. 91 nhóm có input hash khác target; reason counts có thể chồng lấn. Không sửa nhãn legacy, SQLite, frozen corpus hoặc curated v1.

## Giới hạn

Source-only regression cần dữ liệu local được skip có lý do, không thay bằng assertion giả. Fixture không kết nối GitHub thực; provider quota và live API không được kiểm chứng trong phiên này. Worker live chưa tự nạp overlay reconciliation. Nhãn không là ground truth. Kết quả của review hiện tại thay thế những ghi chú pending/các số liệu cũ trong tài liệu lịch sử.
