# Thu thập JD mới và hoàn thiện pipeline bàn giao EDA

## 1. Mục tiêu và điều kiện hoàn thành

Thu thập mới JD IT tại Việt Nam, mọi cấp độ, ưu tiên DevOps, Cloud, AI/ML và Data Engineer. Tất cả bản ghi nghiên cứu phải được tải từ web trong đợt triển khai. Hai ZIP cũ dùng để tham khảo code và kiểm thử.

- Thu thập toàn bộ JD tìm thấy trong danh sách việc làm IT, các truy vấn nghề và sitemap phù hợp của những nguồn đã khảo sát.
- Mỗi đợt có danh sách URL và thời điểm bắt đầu được lưu lại. Kết thúc khi đã xử lý hết hàng đợi hoặc ghi nhận rõ phần bị giới hạn bởi nguồn.
- Mục tiêu tối thiểu **1.000 JD unique đủ điều kiện**, trong đó mỗi nhóm ưu tiên có ít nhất **50 JD unique**. Tiếp tục xử lý hàng đợi sau khi đạt mốc này.
- “Mới” được hiểu là mới thu thập trong đợt triển khai. Giữ nguyên ngày đăng có bằng chứng, cho phép thiếu ngày.
- Hoàn thành toàn bộ yêu cầu Người 1 khi có corpus `EDA_READY`, notebook bàn giao chạy được, các bài kiểm thử bắt buộc đạt và cập nhật/khôi phục hoạt động.
- Nếu thiếu số lượng, thiếu kiểm tra thủ công hoặc nguồn chưa sử dụng được, báo rõ từng mục chưa nghiệm thu, bằng chứng và cách bổ sung.

Giữ các quyết định đã chốt về chạy local, miễn phí và chuẩn bị cập nhật theo lệnh. Nhãn nghề/kỹ năng tự động được ghi là sơ bộ. Gold labels và đánh giá F1 thuộc phần phối hợp với P2/P4.

## 2. Thu thập mới theo PDF và kiểm chứng từng nguồn

**Khảo sát ITviec → TopCV → CareerViet → TopDev**, theo thứ tự trong plan gốc. PDF cung cấp cách triển khai adapter, parser và các file code để tái sử dụng.

Với mỗi nguồn, xác định trang danh sách, cách phân trang, trang chi tiết, định dạng URL/ID, dữ liệu có cấu trúc và điều kiện truy cập liên quan. Lưu URL bằng chứng, thời điểm kiểm tra, kết luận và lý do. Các trạng thái `pending` cũ phải được kiểm tra lại.

**Cách lấy và đọc dữ liệu**

- Dùng `httpx` lấy HTML/JSON và BeautifulSoup tách nội dung.
- Dùng Playwright cho trang cần JavaScript để hiển thị nội dung trong điều kiện truy cập của nguồn.
- Với TopCV, kiểm chứng endpoint `job-view-detail?id=…` được PDF mô tả, đối chiếu kết quả với JD hiển thị. Sửa bộ nhận dạng ID để hỗ trợ các dạng URL thực tế, gồm `/123.html` và `…-j123.html` khi gặp.
- Ưu tiên dữ liệu có cấu trúc nếu đầy đủ và khớp trang hiển thị. Parser riêng của từng nguồn phải tách nội dung JD khỏi menu, quảng cáo và việc làm liên quan.
- Các phương án Zyte/dịch vụ trả phí và vượt chặn trong PDF nằm ngoài cấu hình triển khai đã chốt. Khi gặp giới hạn truy cập, lưu nguyên nhân, tiếp tục nguồn khác và chuẩn bị yêu cầu bổ sung cụ thể.
- Ngày đăng lấy từ bằng chứng trên trang hoặc phản hồi nguồn. Giữ riêng ngày thu thập. Bỏ cách suy ngày từ URL mà PDF đề xuất.

**Chạy thử trước khi mở rộng**

1. Tải tối đa 100 trang chi tiết mỗi nguồn, hoặc toàn bộ nếu ít hơn.
2. Lưu HTML/JSON gốc và metadata trước khi parse.
3. Kiểm tra ít nhất 95% trang chi tiết hợp lệ lấy được chức danh và JD.
4. Đối chiếu 20 mẫu hoặc toàn bộ nếu ít hơn, ghi lại kết quả và người/công cụ kiểm tra. Kiểm tra của agent được ghi đúng nguồn thực hiện.
5. Sửa parser và chạy lại từ raw nếu lấy sai nội dung, cắt mất yêu cầu hoặc lẫn việc làm liên quan.

**Mở rộng và quản lý hàng đợi**

- Khám phá cả danh mục IT và alias nghề Việt/Anh. Từ khóa ưu tiên quyết định thứ tự xử lý.
- Một request đồng thời mỗi domain, cách nhau tối thiểu 5 giây hoặc theo giới hạn chặt hơn của nguồn. Timeout 30 giây, tối đa 3 lần thử cho lỗi tạm thời, tôn trọng `Retry-After`.
- Sau mỗi 200 trang chi tiết, tính lại số JD mới đủ điều kiện, số trùng và độ phủ bốn nhóm ưu tiên.
- Lưu riêng các kết quả thành công, hết hạn, ngoài phạm vi, lỗi parse và lỗi truy cập. Có checkpoint để tiếp tục hàng đợi sau gián đoạn.

## 3. Pipeline xử lý và giao diện bàn giao

Xây package Python theo collection, preparation, enrichment, quality và release. Dùng SQLite lưu trạng thái chạy, Parquet lưu các bảng đầu ra, YAML/JSON lưu cấu hình và phiên bản.

Giữ lệnh audit cũ hoạt động. Cung cấp CLI gồm `audit`, `collect`, `prepare`, `enrich`, `validate`, `release`, `update`, `rollback`, cùng lệnh `run` điều phối toàn bộ chuỗi. Mỗi lần chạy nhận cấu hình và run ID rõ ràng, ghi log và hỗ trợ resume.

**Lưu và chuẩn hóa**

- Mỗi JD truy được về nguồn, URL/ID, thời điểm tải, raw locator và checksum.
- Giữ chức danh gốc, description, requirements và benefits riêng. Chuẩn hóa Unicode/whitespace, giữ các ký hiệu `C++`, `C#`, `.NET`, `CI/CD`.
- Giữ trạng thái thiếu dữ liệu cho ngày, lương, cấp độ và địa điểm. Tách remote khỏi địa điểm.
- Kiểm tra độ đầy đủ bằng nội dung chính và cấu trúc trang. Listing snippet, trang lỗi hoặc JD bị cắt được đưa vào danh sách cần xử lý.
- Mỗi bản ghi có eligibility riêng cho phân tích kỹ năng, nghề và thời gian. Loại thông tin liên hệ cá nhân không cần thiết khỏi bản bàn giao.

**Trùng, đăng lại và sửa nội dung**

- Tách source record, observation, revision, content cluster và leakage group theo plan gốc.
- Cùng tin và nội dung qua hai lần tải tạo thêm observation.
- Nội dung thay đổi tạo revision mới và giữ revision cũ.
- Tin giống nhau ở nhiều URL/nguồn giữ toàn bộ provenance, dùng một đại diện trong bảng đếm kỹ năng.
- Exact match chỉ tự gộp khi metadata tương thích. Khác công ty, địa điểm hoặc cấp độ phải được xử lý theo bằng chứng.
- Tìm near-duplicate bằng shingles/MinHash, seed cố định và Jaccard khởi tạo 0,80. Xuất hàng chờ review. Các nhóm chưa giải quyết được giữ ngoài view dùng kết luận.
- Chọn một JD thực làm đại diện, giữ mapping từ tất cả thành viên đến đại diện.

**Nhãn sơ bộ và tập thí nghiệm**

- Dùng taxonomy và alias có phiên bản. Vai trò mơ hồ giữ `unknown/ambiguous`.
- Skill có canonical ID, đoạn chứng minh, field, offsets và revision tương ứng.
- Khi đếm tần suất, mỗi skill chỉ tính một lần trong một JD.
- Chia train/dev/test 70/15/15 theo leakage group, seed cố định; lưu split để những lượt cập nhật sau giữ ranh giới đã chốt.
- Tạo mẫu annotation phân tầng 150 JD hoặc toàn bộ nếu ít hơn, kèm hướng dẫn gán nhãn. Đánh giá bằng gold để `PENDING` đến khi có nhãn người độc lập.
- Đếm độ phủ nghề bằng nhãn sơ bộ và ghi rõ cách đếm. Một JD có thể thuộc nhiều nhóm, tổng corpus vẫn đếm mỗi JD một lần.

**Bản bàn giao**

Xuất các bảng curated JDs, source records, observations, revisions, provenance, skills, duplicate members và split manifest. Tạo ba view gồm skill corpus, posting history và observation history.

Notebook phải đọc được một release cố định, tái tính missingness, độ phủ, ảnh hưởng dedup và truy từ skill về JD/raw. Chỉ đổi con trỏ `current` sau khi candidate vượt các hard gate.

## 4. Kiểm thử và nghiệm thu toàn bộ

Lập bảng đối chiếu từng yêu cầu của plan với mã xử lý, kiểm thử và kết quả thực chạy. Các tiêu chí chính gồm:

| Phần | Điều kiện nghiệm thu |
|---|---|
| Dữ liệu mới | 100% JD nghiên cứu có raw được tải trong đợt mới và truy vết được |
| Parser | Pilot đạt ngưỡng, mẫu đối chiếu không có lỗi lấy nhầm nội dung nghiêm trọng |
| Chất lượng | Schema, ID, khóa liên kết hợp lệ; bản bị loại hoặc cách ly có lý do |
| Số lượng | Đạt 1.000 JD unique và 50 JD mỗi nhóm ưu tiên, kèm cách xác định nhóm |
| Dedup | Các tình huống ở mục 3 của plan gốc đều có kiểm thử; mapping giữ được nguồn và lịch sử |
| Evidence | 100% spans xuất ra khớp đúng text và revision |
| Split | Không có leakage group xuất hiện trong nhiều tập |
| Đối soát | Tổng đầu vào bằng accepted + quarantined + excluded; dedup có đối soát riêng |
| Tái lập | Cùng raw/config tạo cùng dữ liệu logic và chỉ số |
| Bàn giao | Notebook chạy từ release và tái tính được QA |
| Cập nhật | Hai lượt update, resume sau lỗi và rollback đều được kiểm thử |

Bộ kiểm thử phải bao gồm trang bị chặn, JSON sai cấu trúc, thiếu field, tin hết hạn, URL tái sử dụng, thay ngày nhưng giữ nội dung, thay nội dung, trùng giữa nguồn và dữ liệu mới trùng test set.

Mô phỏng lỗi sau tải raw, giữa lúc xử lý và trước publish. Kiểm tra rerun không nhân đôi JD, lỗi parse chưa được đánh dấu xử lý thành công, release cũ còn dùng được khi candidate fail. Kiểm tra batch và cache để dữ liệu không đổi được tái sử dụng.

Cơ chế update giữ ba checkpoint tải raw, xử lý và phát hành. Dùng watermark với overlap 14 ngày khi thời gian nguồn đáng tin, còn lại đối chiếu ID/hash trong listing. Áp dụng ngưỡng cảnh báo missingness và lượng thu như plan gốc, giữ candidate chờ xem xét khi vượt ngưỡng.

## 5. Phần cần chuẩn bị và cách xử lý thiếu sót

Tiếp tục các phần độc lập khi một nguồn hoặc một tiêu chí chưa đạt. Mỗi mục còn thiếu phải có trạng thái, ảnh hưởng, bằng chứng, việc cần bổ sung và người thực hiện.

| Thiếu hoặc lỗi | Cách bổ sung |
|---|---|
| Môi trường Python, thư viện hoặc Chromium | Chuẩn bị môi trường local và dependency có phiên bản, kiểm tra bằng fixture |
| Nguồn chưa xác định được điều kiện sử dụng | Hoàn tất khảo sát; nếu cần đầu vào từ người dùng, nêu đúng nguồn và bằng chứng còn thiếu |
| Nguồn giới hạn truy cập | Lưu lỗi và hàng đợi, tiếp tục nguồn khác; xác định API/export hoặc quyền truy cập phù hợp nếu có |
| Parser không đạt pilot | Sửa và chạy lại từ raw, đối chiếu lại mẫu |
| Thiếu tổng số hoặc một nhóm nghề | Mở rộng alias, listing và các nguồn đã khảo sát; công bố số còn thiếu sau khi xử lý hết phạm vi |
| Near-duplicate hoặc URL reuse chưa rõ | Xuất các bản cần so sánh và hướng dẫn quyết định để người review bổ sung |
| Chưa có người thử notebook | Chuẩn bị lệnh chạy, dependency và checklist để thành viên nhận dữ liệu kiểm tra |
| Chưa có gold labels | Bàn giao 150 mẫu và hướng dẫn cho P2/P4, để trạng thái đánh giá nhãn `PENDING` |

Lưu kế hoạch vào `docs/IT4930_Person1_Implementation_Plan.md`. Báo cáo cuối tại `docs/IT4930_Person1_Completion_Report.md` phải ghi nguồn thực dùng, số JD trước/sau từng bước, kết quả test, file bàn giao và cách đọc. Những yêu cầu chưa đạt phải được nêu rõ cùng cách bổ sung, kể cả khi các phần còn lại đã chạy thành công.
