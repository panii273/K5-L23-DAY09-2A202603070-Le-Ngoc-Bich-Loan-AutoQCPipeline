"""CHECK 6 — Ý kiến thứ hai: so nhãn với một model LỚN HƠN (yolo26l).   ★★★ (khó nhất, đáng điểm nhất)

Test:  pytest tests/test_second_opinion.py -q

Máy kiểm quy tắc, người kiểm ý nghĩa (slide). Các lỗi như thiếu nhãn / gán nhầm lớp hợp lệ / box lỏng
KHÔNG bắt được bằng quy tắc cú pháp. Ta nhờ một model mạnh hơn "nhìn lại" và CHỈ CẢNH BÁO (model cũng có thể sai):
những ảnh bị cờ sẽ vào hàng đợi cho NGƯỜI duyệt.

`preds[stem]` = list `[id_lớp, conf, cx, cy, w, h]` của model (lấy qua `get_preds(ds, cfg, "checker")` nếu preds=None).
`L = ds.valid_boxes(stem)` = list `(id_lớp, cx, cy, w, h)` của nhãn (đã bỏ dòng hỏng).
Ngưỡng ở `cfg["second_opinion"]`: conf, min_area_px, fp_conf, iou_missing, iou_match, iou_loose.

Thuật toán gợi ý, với từng ảnh (bỏ qua ảnh không có trong preds hoặc không có file nhãn):
  P = dự đoán có conf >= conf  VÀ diện tích px (w*W * h*H) >= min_area_px
  Với mỗi dự đoán r trong P: lấy các nhãn có IoU(r, nhãn) >= iou_missing  (cands)
   - không có cands                            -> POSSIBLE_MISSING     (model thấy vật mà nhãn không có box)
   - có cands cùng lớp, tốt nhất IoU < iou_loose -> POSSIBLE_LOOSE_BOX  (đúng vật, box lỏng/lệch)
   - không có cands cùng lớp, nhưng cands tốt nhất IoU >= iou_match (khác lớp) -> POSSIBLE_WRONG_CLASS
  Với mỗi dòng nhãn hợp lệ: nếu IoU với MỌI dự đoán (conf >= fp_conf, không lọc diện tích) đều < iou_missing
                                             -> POSSIBLE_FALSE_POS  (box nhãn không khớp vật nào model thấy; Issue.line = số dòng)

Chi tiết các ca biên (test kiểm đúng các ca này)
- `cands` gồm nhãn MỌI lớp có IoU >= iou_missing; "tốt nhất cùng lớp" = cands cùng lớp có IoU lớn nhất; "tốt nhất khác lớp" tương tự với cands khác lớp.
- Thứ tự quyết định cho mỗi dự đoán: (1) cands rỗng -> MISSING. (2) có cands cùng lớp: IoU tốt nhất < iou_loose -> LOOSE_BOX, ngược lại KHÔNG cờ
  (nhãn đúng lớp đã phủ vật này, kể cả khi còn nhãn khác lớp chồng lên). (3) không có cands cùng lớp: nếu IoU tốt nhất khác lớp >= iou_match -> WRONG_CLASS;
  nếu chỉ có khác lớp với IoU trong [iou_missing, iou_match) -> không cờ gì (mơ hồ: để cho FALSE_POS / lần duyệt khác).
- Một dự đoán sinh tối đa MỘT issue (MISSING / LOOSE_BOX / WRONG_CLASS); một ảnh có thể có nhiều issue.
- Thứ tự issue: theo `ds.image_files()` rồi theo thứ tự dự đoán trong `preds[stem]`, cuối cùng là các FALSE_POS theo số dòng; `Issue.image` = stem, `Issue.line` chỉ đặt cho FALSE_POS.

Lưu ý số dòng: dùng `ds.read_label_lines(stem)` (giữ số dòng gốc, kể cả dòng hỏng/trống) để lấy `Issue.line`; `valid_boxes` KHÔNG giữ số dòng.

Tất cả severity WARN; `Issue.extra` nên có {"conf": ...} hoặc {"iou": ...} (hàng đợi duyệt dùng conf để xếp ưu tiên).

Gợi ý
- `iou_xywh` có sẵn. Dòng nhãn hỏng không được làm script chết (dùng `ds.valid_boxes` và `parse_yolo_line` trong try).
- Kết quả phụ thuộc mạnh vào ngưỡng: calibrate chúng ở Bước 3 thay vì đoán.
"""
from ..common import WARN, Issue, iou_xywh, parse_yolo_line
from ..model_cache import get_preds

CHECK = "second_opinion"


def _label_boxes(ds, stem, n_cls):
    """[(số dòng gốc, (id, cx, cy, w, h))] của các dòng hợp lệ — đọc file 1 lần, giữ số dòng (valid_boxes thì không)."""
    out = []
    for ln_no, text in ds.read_label_lines(stem) or []:
        try:
            b = parse_yolo_line(text)
        except ValueError:
            continue                     # dòng hỏng: label_format đã báo
        if 0 <= b[0] < n_cls:
            out.append((ln_no, b))
    return out


def _judge(r, labels, c):
    """Phân loại MỘT dự đoán r theo thứ tự ưu tiên của docstring. Trả về (mã, extra) hoặc None."""
    cls, conf, box = int(r[0]), float(r[1]), r[2:6]
    best_same = best_other = None       # None = không có ứng viên loại đó
    for _, b in labels:
        iou = iou_xywh(box, b[1:])
        if iou < c["iou_missing"]:
            continue                     # không phải ứng viên
        if b[0] == cls:
            best_same = iou if best_same is None else max(best_same, iou)
        else:
            best_other = iou if best_other is None else max(best_other, iou)
    extra = {"conf": round(conf, 4), "class": cls}
    if best_same is None and best_other is None:                # (1) cands rỗng
        return "POSSIBLE_MISSING", extra
    if best_same is not None:                                   # (2) có cands cùng lớp
        if best_same < c["iou_loose"]:
            return "POSSIBLE_LOOSE_BOX", {**extra, "iou": round(best_same, 4)}
        return None                                             # nhãn đúng lớp đã phủ vật -> im lặng, kể cả có nhãn khác lớp chồng
    if best_other >= c["iou_match"]:                            # (3) chỉ có cands khác lớp
        return "POSSIBLE_WRONG_CLASS", {**extra, "iou": round(best_other, 4)}
    return None                                                 # khác lớp, IoU mơ hồ -> không cờ


MSG = {
    "POSSIBLE_MISSING": "model thấy vật lớp {class} (conf {conf}) mà nhãn không có box",
    "POSSIBLE_LOOSE_BOX": "cùng vật, cùng lớp {class} nhưng box lệch/lỏng (IoU {iou})",
    "POSSIBLE_WRONG_CLASS": "model nói lớp {class} (conf {conf}) nhưng nhãn trùng chỗ lại khác lớp (IoU {iou})",
}


def run(ds, cfg, preds=None):
    c = cfg["second_opinion"]
    if preds is None:
        preds = get_preds(ds, cfg, "checker")
    n_cls = len(ds.classes)
    issues = []
    for img in ds.image_files():
        stem = img.stem
        if stem not in preds or not ds.label_path(stem).exists():
            continue
        size = ds.image_size(stem)
        if not size:
            continue                     # ảnh không mở được: images check đã báo
        W, H = size
        rows = preds[stem] or []
        labels = _label_boxes(ds, stem, n_cls)

        # Lượt 1: dự đoán -> nhãn (chỉ dự đoán tin được và đủ lớn); mỗi dự đoán tối đa 1 issue
        for r in rows:
            if r[1] < c["conf"] or r[4] * W * r[5] * H < c["min_area_px"]:
                continue
            got = _judge(r, labels, c)
            if got:
                code, extra = got
                issues.append(Issue(CHECK, WARN, code, stem, MSG[code].format(**extra), None, extra))

        # Lượt 2: nhãn -> dự đoán (conf >= fp_conf, KHÔNG lọc diện tích)
        fp_boxes = [r[2:6] for r in rows if r[1] >= c["fp_conf"]]
        for ln_no, b in labels:
            best = max((iou_xywh(b[1:], p) for p in fp_boxes), default=0.0)
            if best < c["iou_missing"]:
                issues.append(Issue(CHECK, WARN, "POSSIBLE_FALSE_POS", stem,
                                    f"box nhãn lớp {b[0]} không khớp vật nào model thấy (IoU tốt nhất {best:.2f})",
                                    ln_no, {"iou": round(best, 4), "class": b[0]}))
    return issues
