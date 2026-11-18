"""BƯỚC 2/4 — Sửa tự động những lỗi bắt buộc mà máy sửa được AN TOÀN.   ★★

Test:  pytest tests/test_autofix.py -q

`fix(ds, issues, cfg) -> list[dict]`: duyệt `issues` (chỉ lỗi severity ERROR), sửa thẳng vào thư mục `ds`,
và trả về danh sách thay đổi; mỗi phần tử có khoá: image, line, action, before, after
(đây chính là file `03_fixes.csv` — bằng chứng pipeline đã làm gì, người có thể kiểm lại).

| code lỗi                                       | cách sửa                                    | action           |
|------------------------------------------------|---------------------------------------------|------------------|
| BAD_FORMAT, BAD_CLASS_ID, BOX_ZERO, DUP_BOX    | xoá dòng đó khỏi file nhãn                  | "drop_line"      |
| BOX_OUT_OF_IMAGE                               | cắt box về trong [0,1] (giữ nguyên lớp)     | "clip_box"       |
| MISSING_LABEL_FILE                             | KHÔNG sửa file (máy không thể bịa nhãn): ghi 1 dòng fix, before="(không có file)", after="chuyển người gán" | "needs_label" |
| BAD_CLASS_NAME                                 | ghi lại `names` trong data.yaml đúng `cfg["classes"]` | "rename_classes" |
| DUP_IMAGE_*, LEAK_TEST, CORRUPT_IMAGE, BAD_SIZE| xoá ảnh + nhãn khỏi `ds`                    | "remove_image"   |

Bẫy cần nghĩ tới (có test cho từng cái)
- Một file có NHIỀU dòng lỗi: số dòng trong `issues` là số dòng GỐC. Nếu xoá từng dòng một thì số dòng lệch.
  Gom theo file, rồi ghi lại MỘT lần.
- Sau khi cắt, box có thể không còn diện tích (nằm hẳn ngoài ảnh): lúc đó xoá dòng thay vì ghi box rỗng.
- Một dòng có 2 lỗi (vd. BOX_OUT_OF_IMAGE + DUP_BOX): xoá dòng thắng, chỉ ghi 1 fix `drop_line`, không ghi thêm `clip_box`. Dòng trống ở giữa file vẫn đếm vào số dòng gốc.
- Ảnh vừa bị xoá (DUP_IMAGE_*...) mà còn issue dòng của chính nó: bỏ qua êm, không được báo lỗi/chết.
- Không động tới lỗi WARN (cảnh báo là việc của người). Không sửa file ở `data/raw/` — chỉ sửa `ds`.
- Chạy lần 2 trên dữ liệu đã sửa phải không làm gì thêm (idempotent) — NGOẠI LỆ duy nhất: `needs_label` được ghi lại mỗi lần còn lỗi `MISSING_LABEL_FILE` (vì ảnh vẫn chưa có nhãn).

- `needs_label` KHÔNG tạo file nhãn rỗng (rỗng = "ảnh nền", khác với "chưa gán"). `review_queue` sẽ đẩy ảnh này lên đầu hàng đợi cho người.

Gợi ý: `yaml.safe_load / safe_dump`.
"""
from collections import defaultdict

import yaml

from ..common import ERROR, parse_yolo_line

DROP_CODES = {"BAD_FORMAT", "BAD_CLASS_ID", "BOX_ZERO", "DUP_BOX"}
CLIP_CODE = "BOX_OUT_OF_IMAGE"
REMOVE_CODES = {"LEAK_TEST", "CORRUPT_IMAGE", "BAD_SIZE"}          # + mọi mã bắt đầu bằng DUP_IMAGE_


def _is_remove(code):
    return code in REMOVE_CODES or code.startswith("DUP_IMAGE_")


def _fix(image, line, action, before, after):
    return dict(image=image, line="" if line is None else line, action=action, before=before, after=after)


def _clip(text):
    """Cắt box về trong [0,1]. Trả về dòng mới, hoặc None nếu sau khi cắt box không còn diện tích."""
    cls, cx, cy, w, h = parse_yolo_line(text)
    x1, x2 = max(0.0, cx - w / 2), min(1.0, cx + w / 2)
    y1, y2 = max(0.0, cy - h / 2), min(1.0, cy + h / 2)
    nw, nh = x2 - x1, y2 - y1
    if nw <= 0 or nh <= 0:
        return None
    return f"{cls} {(x1 + x2) / 2:.6f} {(y1 + y2) / 2:.6f} {nw:.6f} {nh:.6f}"


def _remove_images(ds, stems):
    out = []
    for stem in sorted(stems):
        img = ds.image_path(stem)
        lab = ds.label_path(stem)
        if img is None and not lab.exists():
            continue                                   # đã xoá ở lần trước -> idempotent
        if img is not None:
            img.unlink()
        if lab.exists():
            lab.unlink()
        out.append(_fix(stem, None, "remove_image", img.name if img else "(chỉ có nhãn)", "(đã xoá ảnh + nhãn)"))
    return out


def _rename_classes(ds, cfg):
    data = yaml.safe_load(ds.yaml_path.read_text(encoding="utf-8")) if ds.yaml_path.exists() else None
    data = data if isinstance(data, dict) else {}
    want = {i: n for i, n in enumerate(cfg["classes"])}
    if ds.yaml_names() == want:
        return []
    before = data.get("names")
    data["names"] = want
    ds.yaml_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return [_fix("data.yaml", None, "rename_classes", str(before), str(list(cfg["classes"])))]


def _fix_label_file(ds, stem, codes_by_line):
    """Sửa một file nhãn theo số dòng GỐC; đọc 1 lần, ghi 1 lần."""
    path = ds.label_path(stem)
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()    # giữ dòng trống -> chỉ số = số dòng gốc - 1
    out = []
    for ln_no in sorted(codes_by_line):
        if not 1 <= ln_no <= len(lines) or not lines[ln_no - 1].strip():
            continue                                   # số dòng không còn hợp lệ (file đã đổi): bỏ qua êm
        before = lines[ln_no - 1]
        codes = codes_by_line[ln_no]
        if codes & DROP_CODES:                         # xoá thắng cắt: 1 dòng chỉ ghi 1 fix
            lines[ln_no - 1] = None
            out.append(_fix(stem, ln_no, "drop_line", before, ""))
            continue
        try:
            after = _clip(before)
        except ValueError:
            continue                                   # không parse được nhưng không bị báo BAD_FORMAT: không đoán
        if after is None:
            lines[ln_no - 1] = None
            out.append(_fix(stem, ln_no, "drop_line", before, "(box nằm hẳn ngoài ảnh)"))
        else:
            lines[ln_no - 1] = after
            out.append(_fix(stem, ln_no, "clip_box", before, after))
    if out:
        kept = [ln for ln in lines if ln is not None]
        path.write_text("".join(ln + "\n" for ln in kept), encoding="utf-8")
    return out


def fix(ds, issues, cfg):
    errors = [i for i in issues if i.severity == ERROR]

    remove, needs_label, rename = set(), [], False
    line_codes = defaultdict(lambda: defaultdict(set))          # stem -> số dòng -> {mã lỗi}
    for i in errors:
        if _is_remove(i.code):
            remove.add(i.image)
        elif i.code == "MISSING_LABEL_FILE":
            if i.image not in needs_label:
                needs_label.append(i.image)
        elif i.code == "BAD_CLASS_NAME":
            rename = True
        elif i.line is not None and (i.code in DROP_CODES or i.code == CLIP_CODE):
            line_codes[i.image][i.line].add(i.code)

    fixes = _remove_images(ds, remove)
    if rename:
        fixes += _rename_classes(ds, cfg)
    for stem in sorted(line_codes):
        if stem in remove:
            continue                                   # ảnh đã bị loại: issue dòng của nó bỏ qua êm
        fixes += _fix_label_file(ds, stem, line_codes[stem])
    for stem in sorted(needs_label):
        if stem in remove or ds.label_path(stem).exists():
            continue
        fixes.append(_fix(stem, None, "needs_label", "(không có file)", "chuyển người gán"))   # KHÔNG tạo file rỗng
    return fixes
