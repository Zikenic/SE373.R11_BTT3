# SE373.R11 – Bài tập về nhà #3: Dựng Agent Đặt Vé Máy Bay bằng LangChain & LangGraph

* **Môn học:** Kỹ thuật xây dựng hệ thống Agentic AI (SE373.R11)
* **Khoa:** Công nghệ Phần mềm – Trường Đại học Công nghệ Thông tin (ĐHQG-HCM)
* **Sinh viên thực hiện:** Bùi Vạn Khải
* **Mã số sinh viên (MSSV):** 24520719
* **Thời gian hoàn thành:** Tháng 10/2026

---

## 1. Giới thiệu tổng quan (Project Overview)

Dự án hiện thực hóa một hệ thống **AI Agent hỗ trợ đặt vé máy bay** khép kín, an toàn và có kiểm soát dựa trên hệ sinh thái **LangChain** và **LangGraph**. Trọng tâm của bài tập không chỉ dừng lại ở việc gọi mô hình ngôn ngữ lớn (LLM), mà đặt trọng tâm vào **Harness Engineering** — xây dựng khung bảo vệ (harness) nghiêm ngặt xung quanh agent nhằm:
1. Chặn đứng hoàn toàn việc LLM tự ý thay đổi trạng thái ứng dụng trái phép.
2. Ép buộc các quyết định nhạy cảm phải thông qua kiểm tra ràng buộc nghiệp vụ dưới dạng dữ liệu có cấu trúc.
3. Nghiệm thu kết quả hoàn thành bằng logic code thực tế trên cơ sở dữ liệu thay vì tin vào câu trả lời khẳng định suông của mô hình.
4. Cơ chế phát hiện lặp vô hạn và bàn giao có cấu trúc (Handoff) cho người dùng khi gặp trở ngại ngoài tầm kiểm soát.

> **Lưu ý quan trọng:** Toàn bộ dữ liệu chuyến bay, ghế ngồi, lệnh giữ chỗ và xác nhận đặt vé đều được mô phỏng cục bộ trong module `mock_airline.py`. Hệ thống hoàn toàn không gọi API hãng bay thật và không phát sinh bất kỳ giao dịch thanh toán tài chính thực tế nào.

---

## 2. Kiến trúc Hệ thống & Bốn Lớp Harness (System Architecture & Harness)

Hệ thống được thiết kế theo mô hình phân tầng chặt chẽ:

```
[Người dùng / Yêu cầu]
        │
        ▼
[Agent Layer (LangGraph StateGraph)]
   ├─ ReAct
   ├─ Plan-then-Execute
   └─ Hybrid
        │ (Đề xuất Tool & Tham số)
        ▼
[FLIGHT HARNESS - LỚP BẢO VỆ CHẶN BƯỚC]
   ├─ 1. Constraint Layer : Kiểm tra ràng buộc dữ liệu (Chặng bay, Giờ bay, Hạn mức giá, Trạng thái ghế)
   ├─ 2. Permission Layer : Kiểm duyệt quyền ghi (approved=True) & Bảo vệ quyền sở hữu hành khách
   ├─ 3. Completion Layer : Nghiệm thu logic code (Đọc DB, kiểm tra vé confirmed & khớp toàn bộ tiêu chí)
   ├─ 4. Handoff Layer    : Gói bàn giao cấu trúc khi bế tắc (Lý do, Lịch sử thử nghiệm, Câu hỏi can thiệp)
   └─ Safety / Loop Check : Giới hạn bước, phát hiện lặp vô hạn (Repeated Action / Stalls), Retry lỗi tạm thời
        │ (Nếu Harness PASS)
        ▼
[Mock Tools (LangChain @tool)]
        │ (Thực thi đọc/ghi)
        ▼
[Mock Airline Database (Isolated In-Memory State)]
```

### Chi tiết 4 Lớp Harness:
1. **Constraint Layer (`ConstraintLayer`):** Biến toàn bộ yêu cầu của người dùng thành đối tượng dữ liệu máy hiểu được (`FlightConstraints`). Kiểm tra máy tính (machine-checkable) trước mọi thao tác giữ chỗ/đặt vé. Một chuyến bay khởi hành sau 12:00, giá vượt 2.000.000 VND hoặc hết chỗ sẽ bị từ chối ngay lập tức.
2. **Permission Layer (`PermissionLayer`):** Phân chia rõ ràng giữa thao tác chỉ đọc (`search_flights`, `get_flight_details`) và thao tác ghi nhạy cảm (`hold_booking`, `confirm_booking`, `cancel_hold`). Mọi thao tác ghi đều bị chặn nếu chưa có phê duyệt của người dùng (`approved=False`). Đồng thời kiểm tra quyền sở hữu vé, không cho phép truy vấn hoặc sửa đổi vé của hành khách khác.
3. **Completion Layer (`CompletionLayer`):** Tiêu chuẩn nghiệm thu bằng code. Không chấp nhận trạng thái hoàn thành chỉ vì agent nói "Đã đặt vé thành công". Hàm nghiệm thu trực tiếp truy vấn MockAirline để xác nhận: booking tồn tại, trạng thái là `confirmed`, hành khách là `Bui Van Khai`, chuyến bay thỏa mãn toàn bộ tiêu chí.
4. **Handoff Layer (`HandoffLayer`):** Khi không còn chuyến bay phù hợp, người dùng từ chối, hoặc gặp lỗi không thể khắc phục, Harness lập tức xuất gói bàn giao (`HandoffPackage`) chứa trạng thái, nguyên nhân, danh sách chuyến đã thử, vết thực thi và câu hỏi can thiệp cụ thể.

---

## 3. Ba Mẫu Thiết Kế Agent (Three Agent Design Patterns)

Hệ thống hiện thực độc lập 3 mẫu kiến trúc điều phối thông qua `StateGraph` của LangGraph:

| Mẫu kiến trúc | Cơ chế hoạt động | Đặc điểm nổi bật | Khả năng thích ứng khi SOLD_OUT |
| :--- | :--- | :--- | :--- |
| **ReAct** | Vòng lặp: Suy nghĩ (Reason) → Hành động (Action) → Quan sát (Observe). | Quyết định linh hoạt theo từng bước; quan sát kết quả trả về của tool trước khi chọn bước tiếp theo. | Tự động phát hiện chuyến hết chỗ và chuyển sang chuyến dự phòng VN102 thành công. |
| **Plan-then-Execute** | Lập kế hoạch tĩnh toàn bộ các bước trước → Kiểm duyệt plan → Thực thi tuần tự qua các chốt chặn quyền. | Phân tách rạch ròi giữa giai đoạn lập kế hoạch và giai đoạn chạy; ít bước quyết định controller. | Dừng ngay lập tức tại bước giữ chỗ bị từ chối và bàn giao cho người dùng (đúng nguyên lý kế hoạch tĩnh). |
| **Hybrid** | Lập kế hoạch chiến lược ngắn theo giai đoạn (Khảo sát) → Thực thi từng bước → Giám sát môi trường & Tái lập kế hoạch động khi phát sinh sự cố. | Kết hợp tính định hướng của Plan-Execute với sự linh hoạt của ReAct. | Phát hiện chuyến VN101 hết chỗ, lập tức tái lập kế hoạch nhánh phụ sang chuyến dự phòng VN102 và thành công. |

---

## 4. Cài đặt & Chuẩn bị Môi trường (Installation & Setup)

### Yêu cầu hệ thống:
* Python 3.10+ (Đã kiểm thử toàn diện trên Python 3.12.10 Windows x64)
* Thư viện yêu cầu: `langchain`, `langgraph`, `langchain-openai`, `pydantic`, `python-dotenv`, `python-docx`, `matplotlib`.

### Các bước cài đặt:
```bash
# 1. Di chuyển vào thư mục dự án
cd "SE373.R11_BTT3"

# 2. Tạo và kích hoạt môi trường ảo (khuyến nghị)
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # Trên Windows PowerShell
# source .venv/bin/activate    # Trên Linux/macOS

# 3. Cài đặt các gói phụ thuộc
pip install -r requirements.txt

# 4. Cấu hình biến môi trường
cp .env.example .env
# Chỉnh sửa file .env với API Key của bạn (nếu chạy chế độ LLM thực tế)
```

---

## 5. Hướng dẫn Chạy Chương trình (How to Run)

### 5.1. Chạy CLI Demo tương tác (`run_demo.py`)
CLI cung cấp vết thực thi có cấu trúc rõ ràng:

```bash
# Chạy mẫu ReAct với kịch bản bình thường
python run_demo.py --pattern react --scenario normal

# Chạy mẫu Plan-then-Execute với kịch bản bình thường
python run_demo.py --pattern plan_execute --scenario normal

# Chạy mẫu Hybrid với kịch bản chuyến bay bị hết chỗ (SOLD_OUT)
python run_demo.py --pattern hybrid --scenario sold_out

# Chạy với mô hình LLM thực tế (Gemini 3.8 Flash cấu hình trong .env)
python run_demo.py --pattern react --scenario normal --mode llm

# Chạy kịch bản chờ phê duyệt (hành động ghi bị chặn)
python run_demo.py --pattern react --scenario awaiting_approval --approval no
```

### 5.2. Chạy Bộ Kiểm thử Tự động (`test_agent.py`)
Kiểm thử 17 ca đơn vị bao quát 4 lớp Harness, ranh giới giờ/giá, bảo vệ sở hữu và loop detector:

```bash
python -m unittest -v test_agent.py
```

### 5.3. Chạy Đánh giá Thực nghiệm & Benchmark (`evaluate.py`)
Chạy tự động 21 lượt đánh giá độc lập (3 mẫu × 7 kịch bản), xuất file số liệu `benchmark.json` và `benchmark.jsonl`:

```bash
python evaluate.py --output-dir results
```

---

## 6. Kết quả Thực nghiệm Tóm tắt (Experimental Results)

Dữ liệu thực nghiệm thực tế thu được từ benchmark chạy cục bộ:

| Mẫu thiết kế | Khớp kỳ vọng | SUCCESS | PENDING_REVIEW | HANDOFF | Lượt gọi Tool TB | Bước Controller TB | Thời gian TB |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **ReAct** | **7 / 7 (100%)** | 3 | 2 | 2 | 2.86 | 2.86 | 13.58 ms |
| **Plan-then-Execute** | **7 / 7 (100%)** | 2 | 2 | 3 | 2.71 | 2.71 | 10.73 ms |
| **Hybrid** | **7 / 7 (100%)** | 3 | 2 | 2 | 2.43 | 2.29 | 12.14 ms |

### Kết quả đo lường với LLM thực tế (`ag/gemini-3.8-flash`):
* **ReAct:** Hoàn thành đặt vé thành công sau 4 bước suy nghĩ và 4 lượt gọi tool.
* **Tổng token tiêu thụ:** 9.377 tokens (Prompt: 8.976, Completion: 401).
* **Độ trễ API:** 32.64 giây.

---

## 7. Cấu trúc Thư mục Dự án (Project Structure)

```
SE373.R11_BTT3/
├── README.md                           # Tài liệu hướng dẫn dự án
├── requirements.txt                    # Danh sách thư viện phụ thuộc
├── .env.example                        # Mẫu cấu hình môi trường
├── .gitignore                          # Cấu hình bỏ qua cache và file nhạy cảm
├── flight_domain.py                    # Khai báo dữ liệu có cấu trúc, ràng buộc & status
├── mock_airline.py                     # Cơ sở dữ liệu mock cục bộ và mô phỏng lỗi
├── mock_tools.py                       # 6 công cụ LangChain (@tool có schema Pydantic)
├── harness.py                          # 4 lớp bảo vệ Harness & phát hiện lặp vô hạn
├── agents.py                           # 3 mẫu thiết kế Agent xây dựng bằng LangGraph
├── run_demo.py                         # CLI chạy demo vết thực thi có cấu trúc
├── evaluate.py                         # Benchmark tự động xuất kết quả JSON / JSONL
├── run_llm_eval.py                     # Đánh giá và đo lường token trên LLM thực tế
├── test_agent.py                       # Bộ 17 bài kiểm thử đơn vị unittest
├── generate_report_charts.py           # Sinh biểu đồ chất lượng cao phục vụ báo cáo
└── results/
    ├── benchmark.json                  # Kết quả benchmark chi tiết dạng JSON
    ├── benchmark.jsonl                 # Kết quả benchmark dạng JSONL
    ├── llm_benchmark.json              # Kết quả đo đạc LLM thực tế
    └── figures/                        # Hình ảnh sơ đồ và biểu đồ phục vụ báo cáo
        ├── fig_benchmark_comparison.png
        ├── fig_system_architecture.png
        ├── fig_agent_patterns_flow.png
        └── uit_logo.jpg
```

---

## 8. Tác giả & Bản quyền

* Sinh viên thực hiện: **Bùi Vạn Khải** – MSSV: **24520719**
* Giảng viên lý thuyết: TS. Đỗ Trọng Hợp, ThS. Ngô Ngọc Đăng Khoa, ThS. Phạm Hoàng Hải
* Giảng viên thực hành: Bùi Cao Doanh, Dương Nguyễn Phương Nam, Nguyễn Hiếu Nghĩa, Nguyễn Ngọc Quí, Nguyễn Thị Hoàng Anh, Quan Chí Khánh An
* Trường Đại học Công nghệ Thông tin – ĐHQG-HCM, 2026.
