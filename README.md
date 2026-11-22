# IT4930 — Job Data Engineering Pipeline

Pipeline thu thập và chuẩn bị dữ liệu tuyển dụng, với phân loại role Gemini có checkpoint và kiểm soát quota. **KHDL là project root duy nhất.** Nhãn rule/Gemini là nhãn đề xuất, chưa phải ground truth.

## Cài đặt

Python 3.11; macOS hoặc Linux (các worker sử dụng `flock`).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

Chỉ khi cần Gemini, tạo `.env` từ `.env.example` nếu chưa có rồi điền key của bạn. Không commit key. Crawler trình duyệt là tùy chọn, dùng `requirements-crawlers.txt`. Unit tests và fixture integration chạy offline, không cần key hoặc dataset local. Các regression tests trên dữ liệu thật tự skip khi dataset chưa có.

## Chạy pipeline

```sh
# Xem stage nào có thể tái sử dụng; không ghi dữ liệu
.venv/bin/python -m src.pipeline status
.venv/bin/python -m src.pipeline all

# Thu thập nguồn: chỉ lệnh có --execute mới tải và ghi snapshot
.venv/bin/python -m src.pipeline ingest --source it_job_posting --execute

# M02 theo thứ tự, tự tiếp tục từ checkpoint hợp lệ, xuất release mới
.venv/bin/python -m src.pipeline all --execute --resume --version v2

# Hoặc bao gồm ingestion và chuẩn bị corpus M03 offline trong một lệnh
.venv/bin/python -m src.pipeline all --with-ingest --execute --resume --version v2 --prepare-corpus --corpus m02_v2

# Chạy tới một stage cùng các dependency trước đó
.venv/bin/python -m src.pipeline normalize --execute

# Đối chiếu nhãn legacy -> M02; artifact riêng, không sửa checkpoint
.venv/bin/python -m src.pipeline reconcile --execute

# Kiểm tra corpus offline, không gọi Gemini
.venv/bin/python -m src.pipeline gemini --corpus m02_v1
```

`--resume` dùng fingerprint input/config/code và checksum output; đây cũng là mặc định. Stage lỗi dừng pipeline và không ghi checkpoint thành công. Curated release đã tồn tại không bị ghi đè: cần version mới nếu input thay đổi. `status --execute` vẫn chỉ xem trạng thái. Dùng riêng `publish --execute --version VERSION` để audit và phát hành staging đã hợp lệ.

Gemini live là thao tác riêng dùng quota:

```sh
.venv/bin/python -m src.classification.runner resume --run-id gemini_full_v1
```

Lệnh này tiếp tục **legacy roles_v8**. Không đổi corpus của run cũ. Corpus `m02_v1` có group IDs M02 riêng; nhãn được chuyển nằm trong `data/reconciliation/transferred_predictions.jsonl`, hàng đợi chưa có nhãn chuyển nằm trong `remaining_candidates.jsonl`. Đây là overlay/hàng đợi riêng, chưa tự seed SQLite của run live mới; không dùng lệnh legacy full rồi giả định nó tự bỏ qua overlay này.

## Thêm nguồn

Thêm nguồn vào `configs/sources.yaml` và allowlist `docs/nguondatagithub.txt`, sau đó khai báo mapping rõ ràng ở `configs/source_adapter_mappings.yaml`. Schema chưa hỗ trợ sẽ báo lỗi; tên repository không đủ để hiểu ngữ nghĩa field. Test `tests/test_new_source_e2e.py` đi thực sự từ registry → ingestion → curated bằng schema giả lập khác biệt; chỉ HTTP được mock.

## Dữ liệu và GitHub

Code, cấu hình, tests và tài liệu được đưa lên Git. `data/`, logs, secrets, môi trường local, SQLite/checkpoint và ZIP bên ngoài được giữ local qua `.gitignore`; repo public không kèm dữ liệu gốc hoặc giấy phép phân phối dataset. Kiểm tra điều kiện từng nguồn trước khi chia sẻ dataset. GitHub Actions chạy bộ tests offline.

Chi tiết: [Architecture](docs/ARCHITECTURE.md), [Pipeline](docs/DATA_PIPELINE.md), [Reconciliation](docs/GEMINI_RECONCILIATION.md), [Test report](docs/TEST_REPORT.md), [GitHub readiness](docs/GITHUB_READINESS.md).
