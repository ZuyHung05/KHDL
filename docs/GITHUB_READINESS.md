# GitHub readiness review

Code có thể chia sẻ để review và chạy tests offline. Chưa push hoặc commit thay người dùng. Không tuyên bố provider Gemini live đã được kiểm thử lại.

## Kiểm tra thực tế

- Bản export chỉ chứa các file không bị Git ignore chạy được tests mà không có dataset, .env hay checkpoint local: 86 PASS, 8 SKIP (regression cần dữ liệu local), 14 cảnh báo deprecation của matplotlib/pyparsing.
- Không phát hiện mẫu Google API key, GitHub token hoặc private-key header trong các file dự kiến đưa lên Git. Đây là kiểm tra pattern, không bảo đảm phát hiện mọi loại secret.
- Không có file dự kiến commit lớn hơn 5 MiB. `pip check`: không có dependency bị hỏng trong môi trường hiện tại. Chưa thử cài mới dependency bằng network trong phiên này.
- `git check-ignore` xác nhận .env, SQLite checkpoint, data và ZIP ngoài project bị loại khỏi Git. Không in nội dung key.
- CI offline được cấu hình trong .github/workflows/tests.yml; chưa chạy trên GitHub Actions thật.

## Giữ local qua .gitignore

Toàn bộ data/ (raw, staging, curated, manifests, reconciliation, SQLite/checkpoints), logs/, reports/, .env và các env variant, .venv, Python/pytest caches, .DS_Store, ZIP ngoài project và các README/ignore backup của lần di chuyển root. Hai archive docs khoảng 1,2 GiB được giữ local, không đưa lên Git. Code/config/tests/docs hiện hành vẫn nằm trong source distribution.

Không xóa bất kỳ dataset hoặc checkpoint nào. Không git reset, git add, commit hoặc push. Khi chuẩn bị commit, xem `git status --short` và `git diff --cached --stat`; chỉ commit nội dung đã review. Dữ liệu không kèm repo, nên người clone cần chạy ingestion/fixture hoặc có snapshot riêng để chạy real-data regression.

## Giới hạn vận hành

Reconciliation tạo overlay và remaining queue; chưa tự seed nhãn vào SQLite của worker live mới. Không dùng legacy full runner rồi giả định tự bỏ qua overlay. 104 nhãn đã chuyển vẫn là đề xuất. Tests fixture mock HTTP transport, không chứng minh upstream GitHub luôn giữ schema hay license dữ liệu cho phép redistributing.
