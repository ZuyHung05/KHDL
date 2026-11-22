# Architecture

KHDL là root duy nhất. `src/collection` sở hữu registry, tải/validate snapshot và manifest; `src/preparation` sở hữu adapters, quality, cleaning, dedup, normalization, eligibility và curated publishing; `src/classification` sở hữu frozen corpora, input redaction, taxonomy validation, Gemini client, quota, cache và reconciliation.

`src/pipeline.py` điều phối qua các CLI module hiện có, tránh nhân đôi xử lý. Theo mặc định nó chỉ lập danh sách stage. `all --execute` chạy M02; tùy chọn with-ingest và prepare-corpus nối M01 và M03 offline. Live API được tách thành lệnh explicit của classification.runner. Cache/state được persist trong data/pipeline_state.json và khóa bằng flock; mỗi stage phải thành công, có đủ output hợp lệ và input không thay đổi trước khi checkpoint được ghi atomic.

Dedup stage mới xây dataset hiện tại trước khi audit, nên hỗ trợ workspace mới và snapshot thay đổi, không phụ thuộc baseline dedup_v1 lịch sử. Curated publishing hỗ trợ report audit thủ công theo corpus như một report tùy chọn. Dữ liệu và checkpoint không thuộc source distribution GitHub.

Reconciliation không ghi đè nhãn: provenance, exact submitted input hash, versions và evidence quyết định một overlay theo M02 group ID. Pending, conflict và thiếu bằng chứng không được chuyển. Các rule/prediction đều là đề xuất, không là ground truth. Worker live chưa tự nạp overlay; xem GEMINI_RECONCILIATION.md trước khi chạy corpus mới.
