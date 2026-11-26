# IT4930 — Thu thập dữ liệu việc làm IT

Project hỗ trợ hai kiểu thu thập độc lập:

- GitHub CSV qua `src/collection/github_ingestion.py`, có checksum, snapshot theo revision và manifest.
- Tin tuyển dụng từ ITviec, TopDev, VietnamWorks, TopCV và LinkedIn qua `crawlers/`, sau đó đóng gói JSONL thành snapshot có checksum và manifest.

Để chạy lần lượt cả năm nguồn, mở notebook [02_crawl_all_sources.ipynb](notebooks/02_crawl_all_sources.ipynb) và chạy các cell từ trên xuống. Notebook nhúng toàn bộ mã crawler, fetcher, checksum và manifest; nó không cần import file nào từ project IT4930 hay vietnam-it-job-trends sau khi được gửi đi. Cell đầu cài thư viện/browser, các cell tiếp theo dựng runtime và chạy theo thứ tự ITviec → LinkedIn → TopCV → TopDev → VietnamWorks, fetch description headless và lưu snapshot sau từng nguồn. Notebook chia cell listing/description riêng cho từng nguồn, lưu checkpoint từng JD và giữ staging để chạy tiếp. Listing LinkedIn/TopCV tự thử cuộn/chuyển trang có giới hạn; LinkedIn vẫn cần đăng nhập qua cửa sổ trình duyệt. Coverage và lỗi phải được kiểm tra sau chạy; không bảo đảm thu thập được toàn bộ tin hoặc description đầy đủ trên các website.

## Cài đặt crawler

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-crawlers.txt
playwright install webkit
```

Các crawler public dùng Google Chrome đã cài trên máy; LinkedIn dùng WebKit do Playwright cài.

Chạy từ thư mục `IT4930`. Ví dụ:

```bash
python -m src.collection.crawler_ingestion --source itviec -- --pages 34
# hoặc
make crawl-vietnamworks
```

Nguồn được chọn trong `--source`: `itviec`, `topdev`, `vietnamworks`, `topcv`, `linkedin`. Tham số sau `--` được chuyển nguyên vẹn cho crawler. TopCV và LinkedIn cần thao tác trình duyệt; nhấn Ctrl+C trong cửa sổ tiến trình để kết thúc phần crawl và bắt đầu đóng gói snapshot. LinkedIn cần đăng nhập thủ công lần đầu.

## Quy trình và cấu trúc snapshot

Hai pha được chạy bằng hai lệnh tách biệt. `make crawl-<nguồn>` chỉ lấy danh sách URL, lưu vào staging rồi trả về terminal. Khi bạn sẵn sàng, chạy `make crawl-description SOURCE=<nguồn>` để fetch description và tạo snapshot cuối. Ví dụ:

```bash
make crawl-itviec
# Terminal trả về sau khi crawl danh sách xong
make crawl-description SOURCE=itviec HEADLESS=1
```

`HEADLESS=1` chạy Chrome ẩn trong bước fetch description. Bỏ `HEADLESS=1` nếu muốn nhìn cửa sổ trình duyệt trong lúc fetch. Có thể gọi trực tiếp module đã tích hợp thay vì script của repo crawler cũ:

```bash
python -m src.collection.crawler_ingestion --source itviec --phase descriptions --headless
```

Thứ tự thao tác bạn dự kiến:

```bash
make crawl-itviec
make crawl-description SOURCE=itviec HEADLESS=1
make crawl-linkedin
make crawl-description SOURCE=linkedin HEADLESS=1
make crawl-topcv
make crawl-description SOURCE=topcv HEADLESS=1
make crawl-topdev
make crawl-description SOURCE=topdev HEADLESS=1
make crawl-vietnamworks
make crawl-description SOURCE=vietnamworks HEADLESS=1
```

TopCV và LinkedIn cần bạn crawl listing trong cửa sổ trình duyệt rồi nhấn Ctrl+C để kết thúc pha listing; terminal runner sẽ chờ crawler dừng và trả về. Sau đó bạn chủ động gọi lệnh description. LinkedIn dùng phiên đăng nhập đã lưu. VietnamWorks có description trong API listing nhưng vẫn chạy qua bước fetch chi tiết để chuẩn hóa/hoàn thiện.

Mỗi nguồn có thư mục và revision riêng:

```text
data/raw/jobs/
  itviec/
    <snapshot_sha256>/
      listings.jsonl       # dữ liệu listing đã crawl
      jobs.jsonl            # bản ghi sau khi fetch description
      details_errors.jsonl  # chỉ có nếu một số URL fetch lỗi
      manifest.json
  topcv/
    <snapshot_sha256>/...
```

Listing chờ fetch description nằm trong `data/staging/`; staging được giữ lại nếu bước description lỗi để có thể chạy lại. Sau khi đóng gói snapshot thành công, staging tương ứng được dọn. Manifest ghi checksum từng file, số bản ghi listing/final, số tin có description, tỷ lệ description, số lỗi và tham số crawl. Nếu toàn bộ nội dung snapshot giống lần gần nhất, hệ thống không tạo bản sao mà ghi `SKIPPED_UNCHANGED` vào `logs/collection.jsonl`. Nếu có lỗi fetch description, các URL lỗi được giữ trong `details_errors.jsonl` và manifest thể hiện coverage thực tế.

LinkedIn dùng profile trong `data/linkedin-profile-webkit/`; profile và staging đã được thêm vào `.gitignore`, không commit cookie hoặc session đăng nhập.

## GitHub ingestion

Collector GitHub cũ vẫn dùng riêng cho nguồn file có URL và revision:

```bash
python -m src.collection.github_ingestion --config sources.json
```

Hai collector cùng ghi log vào `logs/collection.jsonl`, nhưng lưu snapshot ở nhánh thư mục riêng để không đè dữ liệu lên nhau.

## M01 GitHub ingestion (đang hoàn thiện)

Từ thư mục `IT4930`, cài dependency bằng `pip install -r requirements-m01.txt` rồi chạy `python -m src.collection.runner --mode update`. Có thể thêm `--source it_job_posting` hoặc `--dry-run`. Lệnh `python -m src.collection.runner --mode report` tạo lại thống kê từ latest pointers. Tùy chọn `GITHUB_TOKEN` giúp tăng hạn mức API.

Cấu hình nguồn và taxonomy ở `configs/`. File gốc được tải vào staging, kiểm tra rồi publish theo checksum; log tại `logs/m01.jsonl`. Snapshot cũ `main` và commit SHA chưa được nhập vào cấu trúc mới. Bộ test hiện còn hạn chế; pipeline chưa hoàn tất toàn bộ tiêu chí nghiệm thu M01.

## Phân loại role bằng Gemini (đang triển khai)

Phân loại Gemini tạo **nhãn đề xuất**, không sửa raw hoặc ghi đè nhãn rule. Corpus được cố định theo snapshot, checksum và taxonomy; `roles_v8` là corpus đã chuẩn bị cho lượt tiếp theo; thử nghiệm trước dùng `roles_v3`. File kết quả và tệp kiểm tra payload có thể chứa nội dung JD, được giữ trong `data/curated/` và không commit.

```bash
# Chạy từ IT4930; dùng môi trường Python 3.11 của dự án
pip install -r requirements-m01.txt -r requirements-classification.txt
python -m src.classification.runner preflight --corpus roles_v8 --dry-run
python -m src.classification.runner export-sample --corpus roles_v8 --stage smoke50
```

Lệnh export tạo tệp JSONL để người vận hành xem cục bộ; nếu tệp đã tồn tại, xem tệp đó thay vì ghi đè. Kiểm tra từng payload dự kiến gửi trước khi dùng `--privacy-reviewed`. Bộ lọc email, điện thoại, link và liên hệ chỉ hỗ trợ giảm lộ thông tin, không bảo đảm ẩn danh. Theo [chính sách giá Gemini](https://ai.google.dev/gemini-api/docs/pricing), nội dung Free Tier có thể được dùng để cải thiện sản phẩm; kiểm tra chính sách hiện hành trước khi gửi dữ liệu.

Sao chép `.env.example` thành `.env`, thiết lập `GEMINI_API_KEY` và `GEMINI_MODEL` trên máy; biến môi trường có sẵn được ưu tiên. Không đưa khóa lên Git hoặc chat. Cấu hình quota trong `configs/gemini_roles.yaml` là giới hạn cục bộ; cần đối chiếu lại AI Studio. Các request khác ngoài cơ sở dữ liệu cục bộ không được tự động đếm, do đó số còn lại thực tế có thể thấp hơn. Hệ thống không tự chuyển model hoặc tier.

Thử nghiệm vừa qua có 5 request phân loại (2 lỗi 400, 3 lỗi 504) và thêm 3 request kiểm tra metadata model. Ba request metadata chưa được tính trong giới hạn ban đầu; hệ thống đã bổ sung reservation ước lượng thời điểm cho chúng, và từ nay tính cả metadata vào giới hạn nội bộ. Google có thể áp quota khác cho loại request này. Đã dừng gọi API theo yêu cầu. Điều chỉnh cấu hình chỉ cho một run mới; resume dùng cấu hình đã đóng băng. Chỉ sau khi có ngân sách request mới, xem lại đúng 5 payload và được phép chạy tiếp, có thể tạo một run mới (không dùng lại ID đã tồn tại):

```bash
python -m src.classification.runner pilot --corpus roles_v8 --stage pilot5 --run-id pilot5_new --privacy-reviewed
python -m src.classification.runner resume --run-id pilot5_new
```

Mọi request, bao gồm kiểm tra metadata model, được cấp phát quota trước khi gửi; timeout không rõ usage vẫn giữ reservation. Khi nhận HTTP 429 hoặc chạm giới hạn, hệ thống dừng và checkpoint. Một crash sau khi API trả lời nhưng trước khi commit có thể gây gọi lại khi resume; không cam kết exactly-once. Chi phí ước tính để trống nếu chưa xác minh giá áp dụng cho model; giá trị ước tính không phải dữ liệu billing. `usage_summary.json`, `predictions.jsonl`, `review_queue.jsonl` và `events.jsonl` nằm trong thư mục run.

Pilot 200 và gold độc lập chưa được thực hiện; chưa có bằng chứng để mở full. Mẫu pilot là mẫu phân tầng theo nhóm content hash, xác suất lưu trong `samples.json` là xác suất có điều kiện sau khi bỏ smoke. Các tầng còn lại sau smoke đều có mẫu trong pilot của `roles_v8`; tỷ lệ lấy mẫu khác nhau giữa các tầng. Báo cáo bổ sung ước lượng có trọng số nghịch đảo xác suất cho nhóm input hash sau smoke, cùng metric không trọng số dùng cho gate; ước lượng không đại diện trực tiếp cho từng JD, chưa có khoảng tin cậy và không dùng để mở gate. **Không chạy full** khi chưa có kết quả pilot đạt các ngưỡng trong kế hoạch và xác nhận riêng của người dùng. Alias model có thể thay đổi bên trong ngay cả khi tên phiên bản không đổi; cache không thể phát hiện mọi thay đổi của nhà cung cấp.


Để chuẩn bị các bước tiếp theo sau khi API hoạt động và có ngân sách phù hợp, trước hết phải xem đầy đủ payload của smoke50. Lệnh `pilot --stage smoke50` cần `--privacy-reviewed`; sau đó người kiểm tra tạo JSON gồm `run_id`, `reviewer`, `all_reviewed: true`, `prompt_frozen: true` và danh sách đủ 50 `reviewed_jd_ids`. Pilot 200 dùng `--stage pilot200 --smoke-review <file>` sau khi export và xem `pilot200`. Chỉ chạy khi đã xem dữ liệu và tuân thủ quota.

Gold JSONL phải bao gồm `jd_id`, `role`, `seniority`, `ambiguous`, `multiple_roles`, `evidence` (target/field/quote đúng nguyên văn input đã lọc), `adjudicated`, `adjudicator`, và hai `annotations` có `annotator` khác nhau, `blind: true`, `guideline_version` và `role`. Tập này do hai người gán độc lập và thống nhất bất đồng; không suy gold từ output Gemini. Để kiểm tra phản chứng Cloud, phải có ít nhất một JD gold `non_it` gắn `cloud_counterexample: true`, thực sự nhắc AWS/Azure/GCP (hoặc tên đầy đủ tương ứng), và có response hợp lệ. Nếu pilot không có mẫu phù hợp, có thể cung cấp gold phản chứng độc lập và output từ một run đã hoàn thành cùng corpus/model qua `--cloud-case-run <run_id> --cloud-case-gold <file>`. Mẫu phải tách khỏi pilot theo ID và content hash; output được đối chiếu với checkpoint SQLite. Nếu không có bằng chứng này, gate không mở. Sau đó dùng `evaluate --run-id <pilot200> --gold <file>` cùng hai tùy chọn trên khi cần. Nếu prompt đã được chỉnh dựa trên pilot, đánh dấu `--development-set` và dùng một tập đánh giá độc lập mới trước khi tuyên bố chất lượng.

`full` yêu cầu `--gate-run`, `--privacy-reviewed` và `--confirm-full`; mã kiểm tra lại evaluation, evidence, ngưỡng và phiên bản trước khi gọi API. Xác nhận đó chỉ được dùng sau khi người dùng đồng ý chạy toàn bộ. Thay đổi prompt, model, code xử lý hoặc quota đã đóng băng sẽ không được đưa vào resume cũ: tạo run mới; cache chỉ dùng khi phiên bản tương thích. Với quota 15 request/ngày, 5.915 ứng viên cần nhiều ngày và có thể còn chậm hơn vì retry/review.


// lệnh run gemini LLM : ../.venv/bin/python -m src.classification.runner resume \
  --run-id gemini_full_v1