"""Generate professional charts and diagrams for the university report.
SE373.R11 - BTVN #3: Agent đặt vé máy bay bằng LangChain
Student: Bùi Văn Khải - MSSV: 24520719
"""

import os
import matplotlib.pyplot as plt
import numpy as np

os.makedirs("results/figures", exist_ok=True)
plt.rcParams["font.sans-serif"] = "DejaVu Sans"
plt.rcParams["axes.edgecolor"] = "#cccccc"
plt.rcParams["axes.linewidth"] = 0.8


def generate_benchmark_chart():
    """Figure: Average Tool Calls and Controller Steps across the 3 patterns."""
    patterns = ["ReAct", "Plan-then-Execute", "Hybrid"]
    tool_calls = [2.86, 2.71, 2.43]
    steps = [2.86, 2.71, 2.29]

    x = np.arange(len(patterns))
    width = 0.32

    fig, ax = plt.subplots(figsize=(7, 4.2), dpi=300)
    rects1 = ax.bar(x - width/2, tool_calls, width, label="Lượt gọi Tool trung bình", color="#1f77b4", edgecolor="none", zorder=3)
    rects2 = ax.bar(x + width/2, steps, width, label="Bước quyết định trung bình", color="#ff7f0e", edgecolor="none", zorder=3)

    ax.set_ylabel("Số lượng trung bình / kịch bản", fontsize=11, fontweight="bold")
    ax.set_title("So sánh số lượt gọi Tool và Bước quyết định trung bình trên 7 kịch bản", fontsize=11, fontweight="bold", pad=12)
    ax.set_xticks(x)
    ax.set_xticklabels(patterns, fontsize=10, fontweight="bold")
    ax.legend(frameon=True, facecolor="white", edgecolor="#e0e0e0", fontsize=9)
    ax.grid(axis="y", linestyle="--", alpha=0.5, zorder=0)
    ax.set_ylim(0, 3.8)

    # Add value labels
    for rect in rects1:
        height = rect.get_height()
        ax.annotate(f"{height:.2f}",
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, fontweight="bold", color="#1f77b4")

    for rect in rects2:
        height = rect.get_height()
        ax.annotate(f"{height:.2f}",
                    xy=(rect.get_x() + rect.get_width() / 2, height),
                    xytext=(0, 3), textcoords="offset points",
                    ha="center", va="bottom", fontsize=9, fontweight="bold", color="#ff7f0e")

    plt.tight_layout()
    chart_path = "results/figures/fig_benchmark_comparison.png"
    plt.savefig(chart_path)
    plt.close()
    print(f"Saved: {chart_path}")


def generate_architecture_diagram():
    """Figure: System architecture flowchart."""
    fig, ax = plt.subplots(figsize=(9, 4.8), dpi=300)
    ax.axis("off")

    # Draw boxes
    boxes = [
        {"x": 0.05, "y": 0.55, "w": 0.22, "h": 0.35, "title": "AGENT LAYER\n(LangGraph StateGraph)", "items": ["- ReAct Agent\n- Plan-then-Execute\n- Hybrid Agent\n- Model / Controller"], "color": "#e1f5fe", "border": "#0288d1"},
        {"x": 0.36, "y": 0.15, "w": 0.30, "h": 0.75, "title": "FLIGHT HARNESS\n(4 Lớp Bảo Vệ & Giám Sát)", "items": ["1. Constraint Layer (Data)\n2. Permission Layer (Gate)\n3. Completion Layer (Code)\n4. Handoff Layer (Human)\n--- Safety Limits & Loops ---", "Max Steps | Runtime | Retries\nLoop Detector (Repeated / Stalls)"], "color": "#fff3e0", "border": "#f57c00"},
        {"x": 0.75, "y": 0.55, "w": 0.20, "h": 0.35, "title": "MOCK TOOLS\n(LangChain @tool)", "items": ["- search_flights\n- get_flight_details\n- hold_booking\n- confirm_booking\n- get_booking\n- cancel_hold"], "color": "#e8f5e9", "border": "#388e3c"},
        {"x": 0.75, "y": 0.12, "w": 0.20, "h": 0.32, "title": "MOCK AIRLINE\n(Database & State)", "items": ["- Flights (VN101..)\n- Holds (HLD-..)\n- Bookings (BKG-..)\n- Ownership Check\n- Failure Hooks"], "color": "#f3e5f5", "border": "#7b1fa2"},
    ]

    for b in boxes:
        from matplotlib.patches import FancyBboxPatch
        rect = FancyBboxPatch(
            (b["x"], b["y"]), b["w"], b["h"],
            boxstyle="round,pad=0.01",
            facecolor=b["color"], edgecolor=b["border"], linewidth=1.5
        )
        ax.add_patch(rect)
        ax.text(b["x"] + b["w"]/2, b["y"] + b["h"] - 0.05, b["title"], ha="center", va="top", fontsize=9, fontweight="bold", color="#212121")
        items_str = "\n".join(b["items"])
        ax.text(b["x"] + 0.015, b["y"] + b["h"] - 0.13, items_str, ha="left", va="top", fontsize=7.5, color="#37474f", linespacing=1.3)

    # Draw arrows
    arrows = [
        ((0.27, 0.72), (0.36, 0.72), "Tool Proposed\n(args)"),
        ((0.66, 0.72), (0.75, 0.72), "Authorized\nInvocation"),
        ((0.85, 0.55), (0.85, 0.44), "Mutates / Reads"),
        ((0.75, 0.62), (0.66, 0.62), "Tool Result"),
        ((0.36, 0.62), (0.27, 0.62), "Observation\n(Structured)"),
        ((0.51, 0.15), (0.51, 0.03), "Handoff to Human\n(if unrecoverable)"),
    ]

    for start, end, label in arrows:
        ax.annotate(
            "", xy=end, xytext=start,
            arrowprops=dict(arrowstyle="->", color="#455a64", lw=1.2, mutation_scale=12)
        )
        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2 + 0.02
        if label:
            ax.text(mid_x, mid_y, label, ha="center", va="bottom", fontsize=7, color="#455a64", fontweight="bold")

    ax.text(0.51, 0.01, "Người dùng / Nhân viên hỗ trợ", ha="center", va="bottom", fontsize=8, fontweight="bold", color="#d32f2f", bbox=dict(boxstyle="round,pad=0.3", fc="#ffebee", ec="#d32f2f", lw=1))

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 0.95)
    plt.tight_layout()
    diag_path = "results/figures/fig_system_architecture.png"
    plt.savefig(diag_path)
    plt.close()
    print(f"Saved: {diag_path}")


def generate_patterns_flow_diagram():
    """Figure: Flow comparison between ReAct, Plan-then-Execute, and Hybrid."""
    fig, ax = plt.subplots(figsize=(9, 4.5), dpi=300)
    ax.axis("off")

    patterns = [
        {"y": 0.70, "name": "ReAct", "steps": ["Reason\n(Suy nghĩ)", "Harness Tool\n(Thực thi)", "Observe\n(Quan sát)", "Reason\n(Vòng lặp mới)"], "color": "#e3f2fd", "border": "#1976d2"},
        {"y": 0.40, "name": "Plan-then-Execute", "steps": ["Static Planner\n(Lập toàn bộ plan)", "Plan Validator\n(Kiểm duyệt)", "Approval Gate\n(Chốt ghi)", "Linear Execution\n(Chạy tuần tự)"], "color": "#fff8e1", "border": "#ffa000"},
        {"y": 0.10, "name": "Hybrid", "steps": ["Initial Plan\n(Kế hoạch ngắn)", "Step Execution\n(Chạy từng bước)", "Monitor &\nAdapt", "Dynamic Replan\n(Xử lý phát sinh)"], "color": "#e8f5e9", "border": "#43a047"},
    ]

    for p in patterns:
        ax.text(0.04, p["y"] + 0.08, f"Mẫu: {p['name']}", fontsize=10, fontweight="bold", color=p["border"])
        for i, st in enumerate(p["steps"]):
            bx = 0.22 + i * 0.19
            by = p["y"]
            from matplotlib.patches import FancyBboxPatch
            rect = FancyBboxPatch((bx, by), 0.16, 0.16, boxstyle="round,pad=0.01", facecolor=p["color"], edgecolor=p["border"], linewidth=1.2)
            ax.add_patch(rect)
            ax.text(bx + 0.08, by + 0.08, st, ha="center", va="center", fontsize=7.5, color="#212121", fontweight="bold")

            if i < len(p["steps"]) - 1:
                ax.annotate("", xy=(bx + 0.19, by + 0.08), xytext=(bx + 0.16, by + 0.08),
                            arrowprops=dict(arrowstyle="->", color=p["border"], lw=1.2))

        # ReAct loop arrow
        if p["name"] == "ReAct":
            ax.annotate("", xy=(0.30, p["y"] + 0.16), xytext=(0.87, p["y"] + 0.16),
                        arrowprops=dict(arrowstyle="->", connectionstyle="arc3,rad=-0.25", color=p["border"], lw=1.2, linestyle="--"))
            ax.text(0.58, p["y"] + 0.22, "Lặp cho tới khi hoàn tất / dừng", ha="center", fontsize=7, color=p["border"])

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 0.95)
    plt.tight_layout()
    flow_path = "results/figures/fig_agent_patterns_flow.png"
    plt.savefig(flow_path)
    plt.close()
    print(f"Saved: {flow_path}")


if __name__ == "__main__":
    generate_benchmark_chart()
    generate_architecture_diagram()
    generate_patterns_flow_diagram()
