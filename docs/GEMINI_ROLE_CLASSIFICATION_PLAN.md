# Gemini Flash Role Classification Pipeline — IT4930

**Tài liệu đích:** `docs/GEMINI_ROLE_CLASSIFICATION_PLAN.md`  
**Trạng thái:** Kế hoạch triển khai; chưa ghi file trong Plan Mode, chưa gọi Gemini API.

## 1. Hiện trạng và quyết định thiết kế

Đã đọc code ingestion, registry, taxonomy, reporting và tests. Báo cáo hiện tại xác nhận:

| Chỉ số | Giá trị |
|---|---:|
| Raw records | 9.868 |
| Unique theo dedup hiện tại | 9.558 |
| Unknown | 5.752 |
| Needs Review | 163 |
| Tập ứng viên Gemini | **5.915** |
| Đã có primary role theo luật | 3.643 |

Các số này là baseline để đối soát, không hardcode trong pipeline.

| Thành phần hiện có | Vấn đề | Hướng xử lý |
|---|---|---|
| `runner.py`: `rows`, đọc latest và kiểm tra checksum | Có thể tái sử dụng nhưng đang gắn với điều phối ingestion | Tách phần dựng corpus thành hàm dùng chung |
| Dedup trong `report()` | Chưa có ID bền vững, mất raw locator; chưa gộp exact-content giữa các URL khác nhau | Giữ nguyên hành vi để bảo toàn baseline; bổ sung ID và mapping provenance |
| Phân loại bằng alias title | Nhãn chỉ tồn tại trong bộ nhớ; description không tham gia phân loại | Tách classifier thành hàm thuần, lưu kết quả từng JD |
| Taxonomy YAML | Đủ 13 role/4 family; thiếu định nghĩa, ví dụ phản chứng và version | Bổ sung cấu hình định nghĩa dùng cho Gemini, tham chiếu taxonomy hiện có |
| Mapping nguồn | Chỉ chọn một description; bỏ qua requirements riêng ở một số nguồn | Bổ sung mapping requirements có căn cứ |
| Biểu đồ Matplotlib | Tính số liệu và vẽ trong cùng hàm; ghi vào đường dẫn cố định | Tách thống kê và hàm vẽ nhận bảng cùng output directory |
| Storage | Có raw snapshots/latest, chưa có curated hay checkpoint phân loại | Thêm curated JSONL và SQLite trạng thái/cache |
| Tests | Có 4 test M01, chưa kiểm tra classifier | Giữ test cũ; thêm regression và mock Gemini |
| `.gitignore` | Chưa bảo vệ `.env`, curated, log LLM; `/docs*` đang bị ignore | Thêm ignore phù hợp, ghi rõ ngoại lệ cho tài liệu kế hoạch |

**Các lựa chọn đã chốt:**

- Giữ baseline và quy tắc dedup hiện tại trong phiên bản này.
- Chỉ phân loại 5.915 ứng viên `unknown`/`needs_review` nếu corpus vẫn khớp baseline.
- Kết quả Gemini là **nhãn đề xuất** và có báo cáo riêng; không biến thành ground truth.
- Không tự phân loại lại 3.643 bản đã được luật gán role.
- Không tự chia một issue chứa nhiều vị trí thành nhiều JD; trường hợp này chuyển human review.
- Không bổ sung scheduler, crawler, skill extraction hoặc sửa raw.

## 2. Pipeline và chuẩn bị input

```text
Latest snapshots đã publish
  → Xác minh checksum và đóng băng danh sách snapshot
  → Dựng corpus bằng dedup hiện tại
  → Lưu jd_id, provenance và nhãn rule
  → Chọn unknown / needs_review
  → Tạo input title + description + requirements
  → Loại thông tin liên hệ khỏi bản gửi API
  → Kiểm tra cache và quota
  → Gemini structured output
  → Validate schema, taxonomy, evidence
  → Nhãn đề xuất hoặc human review
  → Checkpoint + báo cáo trước/sau + đánh giá gold
```

### Corpus cố định

Tạo `corpus_manifest.json` chứa snapshot paths, SHA-256, source mappings, taxonomy hash, phiên bản dedup/rule và thời điểm tạo. Mọi pilot/resume/report dùng manifest này, không tự đọc latest mới giữa lượt chạy.

Dựng corpus theo đúng thứ tự registry/file/row hiện tại để giữ lựa chọn đại diện. Lưu:

- `jd_id`: SHA-256 của khóa dedup hiện tại.
- `source_members`: source, file, snapshot hash, row index hoặc issue number.
- `title`, `description`, `requirements`, `company`, URL.
- `rule_status`, `rule_primary_role`, `rule_family`.
- `content_hash` của input phân loại; tách khỏi file checksum và ID.

ID đảm bảo ổn định khi dựng lại cùng corpus/version; không cam kết giữ nguyên khi nội dung hoặc thuật toán dedup thay đổi.

### Requirements theo nguồn

| Nguồn | Cách chuẩn bị |
|---|---|
| `it_job_posting` | Giữ description; requirements rỗng nếu không có trường riêng |
| `dpl_evaluation` | Dùng `raw job`; không dùng các trường kỹ năng/role đã suy luận làm bằng chứng |
| `vietjobs` | Thêm `requirements_text` |
| `careersgovsg` | Thêm `jobRequirements`; giữ `jobResponsibilities` trong description view |
| `ady201m` | Thêm `Yêu cầu ứng viên` |
| `data_job_analysis` | Dùng `JD_Trans`, ghi rõ là text đã chuyển đổi |
| `awesome_jobs_vietnam` | Giữ Markdown body; không suy diễn requirements từ template trống |

Không đổi input dùng để dedup baseline khi bổ sung requirements cho Gemini.

### Bản gửi API

Chuẩn hóa Unicode NFC và xuống dòng; bỏ markup trình bày nhưng giữ nội dung, danh sách và các ký hiệu như `C++`, `C#`, `.NET`. Lưu bản chuẩn hóa cục bộ để kiểm chứng evidence.

Loại email, số điện thoại, tài khoản liên hệ và đoạn “Contact/Application” khỏi payload. Chỉ gửi `jd_id`, title, description và requirements; không gửi URL, raw metadata hoặc thông tin người đăng.

Bộ lọc tự động không được coi là bảo đảm ẩn danh. Kiểm tra thủ công payload mẫu trước lượt 50. Google công bố Free Tier có thể sử dụng nội dung để cải thiện sản phẩm; hướng dẫn vận hành phải nêu rõ điều này. [Chính sách giá và dữ liệu](https://ai.google.dev/gemini-api/docs/pricing)

Nếu cả description và requirements trống, chuyển `REVIEW_REQUIRED/insufficient_text`, không gọi API. Input vượt ngân sách cấu hình chuyển `REVIEW_REQUIRED/input_too_long`; không cắt mất nội dung âm thầm.

## 3. Gemini, taxonomy và schema kết quả

### SDK và cấu hình

Dùng Python 3.11 trong môi trường dự án, `google-genai`, Pydantic, `python-dotenv`; khóa các phiên bản dependency đã kiểm thử khi triển khai. Google khuyến nghị SDK `google-genai`. [Tài liệu SDK](https://ai.google.dev/gemini-api/docs/libraries)

`.env.example`:

```dotenv
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.6-flash
```

Hướng dẫn tạo API key tại AI Studio, sao chép `.env.example` thành `.env` trong `IT4930`, tự điền key trên máy. Biến môi trường được ưu tiên hơn `.env`; không yêu cầu gửi key qua chat.

Chọn `gemini-3.6-flash` làm mặc định ban đầu: tài liệu hiện công bố hỗ trợ structured output và Standard Free Tier. Trước pilot, kiểm tra model còn truy cập được trên project; model không hợp lệ thì dừng, không tự đổi model hoặc tier. [Model](https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash), [giá](https://ai.google.dev/gemini-api/docs/pricing#gemini-3.6-flash)

Sử dụng `client.models.generate_content` với JSON MIME type và Pydantic schema qua cấu hình structured output của phiên bản SDK được khóa. Validate lại ở ứng dụng vì JSON đúng cấu trúc chưa chứng minh nhãn đúng. [Structured output](https://ai.google.dev/gemini-api/docs/structured-output)

Không bật grounding, tools, URL fetching hoặc thực thi code. JD được đặt trong vùng dữ liệu không đáng tin cậy; prompt yêu cầu bỏ qua mọi chỉ dẫn xuất hiện trong JD.

### Định nghĩa 13 role

| Role | Trọng tâm công việc để phân loại |
|---|---|
| Backend | Logic phía server, API và dịch vụ ứng dụng |
| Frontend | Giao diện web và tương tác phía client |
| Fullstack | Trách nhiệm rõ ràng cả frontend và backend |
| Mobile | Phát triển ứng dụng điện thoại |
| Data Analyst | Phân tích dữ liệu, báo cáo, BI phục vụ quyết định |
| Data Engineer | Pipeline dữ liệu, ETL/ELT, kho/lake và hạ tầng dữ liệu |
| Data Scientist | Thống kê, thí nghiệm, mô hình dự đoán và phân tích khoa học |
| AI/ML Engineer | Xây, triển khai và vận hành hệ thống ML/AI |
| DevOps/SRE | CI/CD, vận hành, độ tin cậy, observability và tự động hóa triển khai |
| Cloud | Thiết kế/quản trị kiến trúc và nền tảng cloud, migration, networking, governance |
| Cybersecurity | Bảo mật, phòng vệ, kiểm thử hoặc ứng phó an ninh |
| QA/Testing | Kiểm thử và bảo đảm chất lượng phần mềm |
| Business Analyst | Phân tích yêu cầu nghiệp vụ và kết nối nghiệp vụ–hệ thống |

Quy tắc Cloud bắt buộc: việc dùng AWS/Azure/GCP chỉ là công cụ, không đủ để gán Cloud. Backend dùng S3, Data Engineer dùng BigQuery và DevOps triển khai lên AWS vẫn phân loại theo trách nhiệm chính. Ví dụ phản chứng phải có trong prompt và tests.

Ngoài 13 role, chỉ cho phép:

- `other_it_role`: có bằng chứng là nghề IT nhưng ngoài taxonomy.
- `non_it`: có bằng chứng là nghề ngoài IT.
- `unknown`: thiếu hoặc mâu thuẫn bằng chứng.

Các nhãn ngoại lệ dùng `role_family=null`. Một bản ghi chỉ có một primary role; nhiều vị trí hoặc vai trò ngang nhau → `unknown`, `review_required=true`.

Seniority enum: `intern`, `junior`, `mid`, `senior`, `lead`, `manager`, `unknown`. Chỉ gán từ bằng chứng rõ trong title/nội dung, không suy từ mức lương hoặc số năm bằng một quy tắc ngầm.

### JSON từ Gemini

Ví dụ minh họa, không phải kết quả thật:

```json
{
  "jd_id": "jd_example",
  "primary_role": "Cloud",
  "role_family": "Infrastructure & Security",
  "seniority": "senior",
  "evidence": [
    {
      "target": "primary_role",
      "field": "description",
      "quote": "Design and operate cloud landing zones"
    },
    {
      "target": "seniority",
      "field": "title",
      "quote": "Senior"
    }
  ],
  "review_required": false,
  "review_reasons": []
}
```

Schema cấm field thừa, kiểm tra enum và giới hạn số evidence. Code kiểm tra:

- `jd_id` khớp request.
- Role–family khớp taxonomy.
- Quote là substring chính xác của trường input đã gửi; code tự tính offsets.
- Role khác `unknown` cần evidence role; seniority khác `unknown` cần evidence seniority.
- `unknown` bắt buộc review; không dùng confidence do model tự báo làm ngưỡng chấp nhận.
- JSON sai, evidence giả, refusal/safety block hoặc nhiều vị trí → review với reason riêng.
- Một lần gọi lại có hướng dẫn sửa schema/evidence; không dùng cơ chế “tự sửa” để lặp đến khi ép ra nhãn.

## 4. Batch, cache, checkpoint và lưu trữ

### Cách chạy

V1 dùng batch ở ứng dụng: danh sách nhiều JD nhưng **mỗi request một JD**, concurrency=1. Cách này dễ quy trách nhiệm evidence, retry và cache. Không dùng Gemini Batch API trong thiết kế Free Tier này.

Cấu hình quota gồm RPM, input TPM, RPD, giới hạn request/run và token/run. Người vận hành điền hạn mức thực tế trong AI Studio; chương trình từ chối chạy live nếu chưa cấu hình. Tốc độ vận hành bằng 80% quota đã khai báo.

Quota áp dụng theo project, không theo key; RPD reset theo giờ Pacific. Dùng `America/Los_Angeles`, không giả định offset UTC cố định. [Rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)

- Timeout 60 giây/request.
- Tối đa 3 lần thử với timeout, lỗi kết nối, 429 tạm thời và 5xx.
- Exponential backoff có jitter; ưu tiên `Retry-After`/retry metadata.
- Hết quota ngày: checkpoint rồi thoát `QUOTA_PAUSED`, không lặp retry vô hạn.
- 400 cấu hình, 401/403 quyền/key, model không tồn tại: dừng run rõ lý do.
- Không tự chuyển sang trả phí hoặc model khác.

### Cache và model version

SQLite quản lý `runs`, `tasks`, `attempts`, `cache`, quota counters:

```text
cache_key = SHA256(canonical JSON {
  content_hash,
  model_version,
  prompt_version,
  taxonomy_version,
  preprocessing_version,
  schema_version,
  generation_config_hash
})
```

Hash nội dung chỉ bao gồm các trường dùng để phân loại, không gồm `jd_id`. Nhờ vậy hai ID có cùng input có thể dùng chung kết quả; khi gắn lại kết quả phải kiểm chứng evidence trên input tương ứng.

- Lưu model được yêu cầu và model version thực tế SDK trả về.
- Đầu run live xác nhận model/version; version đổi thì dừng namespace cũ và yêu cầu run mới.
- Nếu API không cung cấp immutable revision, dùng cache namespace vận hành có version; ghi rõ không bảo đảm phát hiện mọi thay đổi bên trong alias.
- Cache cả kết quả hợp lệ cần review để tránh tự gọi lại trường hợp mơ hồ; không cache lỗi mạng như kết quả thành công.
- Local result cache khác với context caching của nhà cung cấp.

Task states: `PENDING`, `RUNNING`, `PROPOSED`, `REVIEW_REQUIRED`, `FAILED`, `RETRY_WAIT`. Cache hit ghi vào metadata task, không tạo JD mới.

Ghi response hợp lệ và checkpoint trong một transaction. Run có khóa liên tiến trình; resume chuyển task đang chạy dở về pending và kiểm tra cache trước. Crash sau khi API trả lời nhưng trước khi lưu có thể gây gọi lặp; log rõ đây là giới hạn, không cam kết exactly-once API.

### Cấu trúc output

```text
IT4930/data/curated/role_classification/
├── corpora/<corpus_id>/
│   ├── corpus_manifest.json
│   ├── corpus.jsonl
│   ├── candidates.jsonl
│   └── samples.json
├── state.sqlite
└── runs/<run_id>/
    ├── run_manifest.json
    ├── predictions.jsonl
    ├── review_queue.jsonl
    ├── events.jsonl
    ├── usage_summary.json
    └── reports/
        ├── coverage_before.csv
        ├── coverage_after_proposed.csv
        ├── role_family_distribution.png
        ├── role_distribution_4panels.png
        ├── evaluation.json
        └── confusion_matrix.png
```

Mỗi prediction lưu thêm content hash, raw locators, versions, timestamp, attempt, cache hit, validation status, baseline label, suggested label và evidence offsets.

Logs chỉ chứa ID, stage, status, error code, latency và usage. Không log key, nguyên prompt, JD hoặc exception chứa payload. Evidence chỉ nằm trong curated result, không trong operational log.

Token báo cáo theo usage metadata: input, output, thinking, cached và tổng nếu provider trả về; không cộng trùng thinking vào tổng output. API timeout không có usage phải ghi `unknown_usage`, không giả định bằng 0.

Chi phí là ước tính theo bảng giá/tier đã lưu trong run; chỉ gọi là chi phí thực tế khi có dữ liệu billing đối soát. Dự án xác nhận Free Tier có giá token 0 thì báo 0 theo tier đó; không suy tier từ API key.

## 5. File cần tạo/sửa và thứ tự triển khai

Các đường dẫn bên dưới tính từ `IT4930`, trừ tài liệu trong `docs` ở workspace.

| Nhóm file | Thao tác và trách nhiệm |
|---|---|
| `src/collection/runner.py` | Giữ CLI ingestion; gọi lại corpus/report helpers sau khi tách |
| `src/collection/corpus.py`, `reporting.py` | Tách dedup hiện tại, provenance, tổng hợp và Matplotlib dùng chung |
| `src/classification/rules.py` | Tách classifier alias, trả nhãn từng JD; không đổi kết quả baseline |
| `src/classification/dataset.py` | Đóng băng corpus, mapping requirements, preprocessing, ID, hash, sampling |
| `src/classification/schema.py`, `gemini_client.py` | Schema/validation và SDK wrapper, quota, timeout/retry |
| `src/classification/state.py`, `runner.py` | SQLite, cache, checkpoint/resume và CLI |
| `src/classification/evaluation.py` | Nhập gold, metrics, confusion matrix, audit proposal |
| `configs/role_taxonomy.yaml` | Giữ 13 role/alias; version bằng hash |
| `configs/role_definitions.yaml`, `gemini_roles.yaml` | Định nghĩa, ví dụ phản chứng và cấu hình vận hành |
| `prompts/role_classification_v1.txt` | Prompt có version, instruction phân loại và xử lý dữ liệu không đáng tin |
| `.env.example`, `.gitignore`, `requirements-classification.txt` | Secret template, bảo vệ output và dependency riêng |
| `tests/classification/` | Fixture tổng hợp, mock API, regression, resume và quota tests |
| README và `docs/GEMINI_ROLE_CLASSIFICATION_PLAN.md` | Hướng dẫn chuẩn bị, vận hành, giới hạn và kế hoạch này |

Thứ tự và nghiệm thu:

1. **Tách code dùng chung:** test M01 cũ vẫn đạt; cùng snapshot tái tạo đúng 9.558/5.752/163.
2. **Đóng băng corpus:** 9.558 ID duy nhất, 5.915 ứng viên; 100% truy được về raw. Chênh baseline phải giải thích trước khi gọi API.
3. **Input + taxonomy + schema:** mapping nguồn đúng; không dùng nhãn kỹ năng suy luận làm evidence; payload mẫu được kiểm tra thông tin liên hệ.
4. **SDK + state:** mock tests đạt; dry-run không cần key và không gọi mạng.
5. **Smoke 50:** chạy live khi có key/quota, kiểm tra thủ công cả 50; sửa lỗi prompt trước khi đóng băng phiên bản pilot.
6. **Pilot 200 độc lập:** đánh giá bằng gold và công bố metrics; không tự chuyển sang full.
7. **Full và resume:** chỉ chạy khi tiêu chí pilot đạt; báo cáo phần hoàn tất, lỗi, review, quota và cache đầy đủ.

## 6. CLI, chất lượng và điều kiện chạy toàn bộ

Các lệnh dự kiến, chạy từ `IT4930` bằng Python của môi trường đã cài dependency:

```bash
python -m src.classification.runner prepare --corpus-id roles_v1
python -m src.classification.runner preflight --corpus roles_v1 --dry-run

python -m src.classification.runner pilot \
  --corpus roles_v1 --stage smoke50 --run-id smoke50_v1

python -m src.classification.runner pilot \
  --corpus roles_v1 --stage pilot200 --run-id pilot200_v1

python -m src.classification.runner evaluate \
  --run-id pilot200_v1 --gold data/audit/gemini_roles/pilot200_gold.jsonl

python -m src.classification.runner full \
  --corpus roles_v1 --run-id full_v1 --gate-run pilot200_v1

python -m src.classification.runner resume --run-id full_v1
python -m src.classification.runner report --run-id full_v1
```

`prepare`, `evaluate`, `report` và dry-run không gọi Gemini. Resume sử dụng đúng manifest, cấu hình và versions của run; cấu hình khác phải tạo run mới. Full dùng cache kết quả smoke/pilot nếu versions khớp.

### Bộ mẫu và gold

- Seed cố định 42; chọn mẫu theo source và trạng thái ban đầu.
- Smoke 50 và pilot 200 không giao nhau, kể cả nhóm có input hash giống nhau.
- Smoke ưu tiên có ví dụ Cloud/DevOps/Backend/Data Engineer, non-IT, JD nhiều vị trí và text thiếu để bắt lỗi thiết kế.
- Pilot lấy mẫu phân tầng từ phần còn lại; lưu xác suất lấy mẫu để diễn giải metrics đúng.
- Người gán gold không xem nhãn Gemini; hai người gán độc lập 200 mẫu và thống nhất bất đồng. Nếu chưa có người gán, đánh giá để `PENDING`.
- Gold lưu role, seniority, ambiguity/multiple-role flag, evidence, người gán và phiên bản hướng dẫn.
- Pilot đã dùng để chỉnh prompt trở thành development set; phải lấy tập đánh giá mới trước khi tuyên bố chất lượng.

### Metrics và ngưỡng triển khai

Báo Precision, Recall, F1 từng lớp, Macro-F1, support, confusion matrix; kèm tỷ lệ abstain/review và tỷ lệ được gán nhãn đề xuất.

Ngưỡng ban đầu để mở full:

- 100% nhãn vào coverage đề xuất vượt schema, taxonomy và evidence validation.
- Schema hợp lệ sau tối đa một sửa lỗi đạt ≥98% trên response nhận được.
- Macro-F1 ≥0,80 trên các lớp có support trong gold, công bố rõ lớp không có mẫu.
- Precision trên các nhãn đề xuất không yêu cầu review ≥0,90.
- Không có lỗi biến JD ngoài IT thành Cloud chỉ vì xuất hiện AWS/Azure/GCP trong bộ kiểm tra phản chứng.

Nếu gold Cloud dưới 20 bản, ghi chất lượng lớp Cloud chưa đủ bằng chứng; đưa các dự đoán Cloud vào human review cho đến khi có tập bổ sung đủ mẫu. Không coi 200 mẫu là bằng chứng bảo đảm cho cả 16 nhãn.

### Kiểm thử bắt buộc

- Regression dedup/rule và số liệu baseline.
- Chỉ chọn unknown/needs_review; không chọn lại role đã xác định.
- JSON hỏng, role ngoài enum, family sai, evidence không có thật, sai ID, refusal, output bị cắt.
- Cloud thực, Backend/Data/DevOps dùng AWS, non-IT nhắc cloud, multi-position issue.
- Timeout, 429/RPD, 5xx, key lỗi, token budget và quota reset.
- Cache hit không gọi API; đổi nội dung/model/prompt/taxonomy/preprocessing làm cache miss.
- Cache hợp lệ nhưng `review_required=true` không tự retry.
- Crash trước/sau response, transaction, resume và khóa đồng thời.
- Log không chứa secrets hoặc JD; raw checksum không thay đổi.
- Các nhóm coverage cộng đúng 9.558; PNG phản ánh bảng, đủ role kể cả số 0.

### Báo cáo sau phân loại

Giữ báo cáo rule baseline và báo cáo đề xuất cùng corpus. Chỉ áp dụng proposal hợp lệ với `review_required=false`; lỗi, mơ hồ và chưa xử lý giữ trạng thái unresolved.

Hiển thị riêng 13 role, `other_it_role`, `non_it`, `unknown`, `needs_review`; không tính `non_it` như độ phủ nghề IT được cải thiện. Hai PNG dùng chung hàm Matplotlib 200 dpi, có `n`, versions, timestamp và chú thích nhãn đề xuất.

Mỗi báo cáo nêu rõ:

- 5.915 ứng viên → cache hits, API calls, proposals, review, failures, pending.
- Số Unknown còn lại và bảng chuyển trạng thái trước–sau.
- Token quan sát được, usage chưa biết, ước tính chi phí và thời gian.
- Giới hạn dedup, issue chứa nhiều vị trí, nhãn luật chưa được kiểm toán và mức đại diện của gold.

Không cam kết số Unknown giảm đến một ngưỡng tùy ý, không coi việc model trả JSON thành công là nghiệm thu chất lượng.
