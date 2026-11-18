"""CHECK 2 — Dòng nhãn YOLO: sai định dạng, ID lớp lạ, box tràn ảnh, box rỗng, box lặp.   (Script 2 trong slide)   ★★

Test:  pytest tests/test_label_format.py -q

Mỗi dòng nhãn: `id cx cy w h` (5 số, toạ độ 0–1). Trả về list[Issue]; `Issue.line` = số dòng (đếm từ 1).

| code             | severity | khi nào                                                                  |
|------------------|----------|--------------------------------------------------------------------------|
| BAD_FORMAT       | ERROR    | không đúng 5 cột số (dùng `parse_yolo_line`, bắt `ValueError`)           |
| BAD_CLASS_ID     | ERROR    | id lớp ngoài 0..len(ds.classes)-1                                        |
| BOX_ZERO         | ERROR    | w <= 0 hoặc h <= 0                                                       |
| BOX_OUT_OF_IMAGE | ERROR    | mép box vượt [0,1] quá `cfg["label_format"]["overflow_tol"]`; extra={"overflow": mức tràn} |
| DUP_BOX          | ERROR    | cùng lớp với một dòng TRƯỚC ĐÓ và IoU > `dup_box_iou`; báo ở dòng SAU    |
| BOX_TINY         | WARN     | cạnh ngắn của box (px) < `min_box_px`  (cần `ds.image_size(stem)`)       |
| BOX_HUGE         | WARN     | w*h > `max_box_frac`                                                     |

Gợi ý
- Mép trái = x - w/2, mép phải = x + w/2 (xem câu hỏi "dòng YOLO nào lỗi?" trong slide).
- Một dòng hỏng (BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO) thì `continue`, đừng kiểm tiếp hình học của dòng đó.
- Dòng thiếu cột làm script của slide dừng giữa chừng: đây là lý do phải `try/except`.
- `iou_xywh(a, b)` có sẵn trong common.py.
- Ngưỡng nằm trong `cfg["label_format"]` — đừng viết cứng số vào code.
"""
from ..common import ERROR, WARN, Issue, iou_xywh, parse_yolo_line

CHECK = "label_format"


def _overflow(cx, cy, w, h):
    """Mức tràn lớn nhất của 4 mép box ra ngoài [0, 1] (0 nếu nằm gọn trong ảnh)."""
    x1, x2 = cx - w / 2, cx + w / 2
    y1, y2 = cy - h / 2, cy + h / 2
    return max(0.0, -x1, x2 - 1.0, -y1, y2 - 1.0)


def _check_file(ds, stem, cfg):
    """Kiểm mọi dòng của một file nhãn; trả về list[Issue] theo thứ tự dòng."""
    c = cfg["label_format"]
    n_cls = len(ds.classes)
    issues = []
    kept = []          # [(số dòng, box)] các dòng đã qua kiểm cú pháp — dùng để so DUP_BOX
    size = None        # (W, H) px, chỉ mở ảnh khi thật sự cần (lần đầu kiểm BOX_TINY)

    for ln_no, text in ds.read_label_lines(stem) or []:
        # 1) cú pháp: hỏng thì báo và bỏ qua phần hình học của dòng này
        try:
            box = parse_yolo_line(text)
        except ValueError as e:
            issues.append(Issue(CHECK, ERROR, "BAD_FORMAT", stem, f"dòng sai định dạng: {e}", ln_no))
            continue
        cls, cx, cy, w, h = box
        if not 0 <= cls < n_cls:
            issues.append(Issue(CHECK, ERROR, "BAD_CLASS_ID", stem, f"id lớp {cls} ngoài 0..{n_cls - 1}", ln_no, {"class": cls}))
            continue
        if w <= 0 or h <= 0:
            issues.append(Issue(CHECK, ERROR, "BOX_ZERO", stem, f"box không có diện tích (w={w}, h={h})", ln_no))
            continue

        # 2) hình học: một dòng có thể dính nhiều lỗi cùng lúc (vd. tràn + trùng)
        over = _overflow(cx, cy, w, h)
        if over > c["overflow_tol"]:
            issues.append(Issue(CHECK, ERROR, "BOX_OUT_OF_IMAGE", stem, f"box tràn ra ngoài ảnh {over:.4f}", ln_no,
                                {"overflow": round(over, 6)}))

        for prev_no, prev in kept:
            if prev[0] == cls:
                iou = iou_xywh(prev[1:], box[1:])
                if iou > c["dup_box_iou"]:
                    issues.append(Issue(CHECK, ERROR, "DUP_BOX", stem, f"trùng box dòng {prev_no} (IoU {iou:.3f})", ln_no,
                                        {"of_line": prev_no, "iou": round(iou, 4)}))
                    break            # chỉ cần một bằng chứng trùng cho mỗi dòng

        if size is None:
            size = ds.image_size(stem) or (0, 0)       # (0, 0): không mở được ảnh -> bỏ qua BOX_TINY
        if size[0] and size[1]:
            short_px = min(w * size[0], h * size[1])
            if short_px < c["min_box_px"]:
                issues.append(Issue(CHECK, WARN, "BOX_TINY", stem, f"cạnh ngắn {short_px:.1f}px < {c['min_box_px']}px", ln_no,
                                    {"short_px": round(short_px, 2)}))
        if w * h > c["max_box_frac"]:
            issues.append(Issue(CHECK, WARN, "BOX_HUGE", stem, f"box chiếm {w * h:.2%} ảnh", ln_no, {"area_frac": round(w * h, 4)}))

        kept.append((ln_no, box))
    return issues


def run(ds, cfg):
    issues = []
    for lf in ds.label_files():                 # đã sắp theo tên -> kết quả ổn định giữa các lần chạy
        issues.extend(_check_file(ds, lf.stem, cfg))
    return issues
