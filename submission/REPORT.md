# Báo cáo Day 09 — Lê Ngọc Bích Loan, 2A202603070

## 1. Kết luận trước
Pipeline kết luận **Hold** (mã thoát 10). Lô raw có **224 ảnh** vào, **22 ảnh bị loại** ở bước nhận, **202 ảnh** vào QC và được xuất làm **bản nháp** `submission/export/clean_v1` (202 ảnh, manifest ghi `decision: Hold`, chưa phát hành).
Sau tự sửa và người duyệt **80/80 ảnh** (đủ ngân sách), không còn lỗi bắt buộc (0 ERROR trong `07_error_list_v3`), nhưng **38/202 ảnh (18,81%)** vẫn còn cảnh báo chưa ai xem, vượt ngưỡng `warn_ratio_hold` = 10% (`08_summary.json`). Nguyên nhân chính: hàng đợi duyệt có **125 ảnh** > ngân sách 80, nên 45 ảnh cuối hàng không được xem.

## 2. Lỗi và phân việc
Số liệu từ `02_error_list_v1` (211 issue trên 147 ảnh + `data.yaml`; mẫu số: 224 ảnh ở bước nhận, 202 ảnh ở QC).

| Mã lỗi | Số ảnh/dòng | Ai sửa (máy/người) | Vì sao |
|---|---:|---|---|
| DUP_IMAGE_EXACT | 8 ảnh | máy: loại ở bước nhận | trùng từng byte (md5) với ảnh đã giữ: chắc chắn, an toàn để loại |
| LEAK_TEST | 5 ảnh | máy: loại ở bước nhận | trùng ảnh test/val, giữ lại sẽ làm sai số đo trên test |
| DUP_IMAGE_NEAR | 4 ảnh | máy: loại ở bước nhận | phash ≤ 10; cả 4 cặp đã mở xem đều là trùng thật (§3) |
| BAD_SIZE / CORRUPT_IMAGE | 3 / 2 ảnh | máy: loại ở bước nhận | cạnh ngắn < 250 px hoặc không mở được: không dùng để train |
| BOX_OUT_OF_IMAGE | 8 dòng / 8 ảnh | máy: `clip_box` (8 dòng) | cắt mép về [0,1], giữ lớp; vd. `img_0078` dòng 2: `0 1.000018 … 0.059964` → `0 0.985018 … 0.029964` |
| DUP_BOX | 7 dòng / 7 ảnh | máy: `drop_line` | cùng lớp, IoU > 0.9 với dòng trước: giữ dòng đầu, xoá dòng sau |
| BAD_CLASS_ID | 6 dòng / 6 ảnh | máy: `drop_line` | id lớp ngoài 0..3 (vd. `93` ở `img_0020` dòng 3): không đoán được lớp đúng |
| BOX_ZERO | 4 dòng / 4 ảnh | máy: `drop_line` | box không có diện tích |
| BAD_FORMAT | 3 dòng / 3 ảnh | máy: `drop_line` | dòng có `nan`/thiếu cột (vd. `img_0014` dòng 1) |
| BAD_CLASS_NAME | 2 issue / `data.yaml` | máy: `rename_classes` | `Person`, `Bus` → đúng `cfg["classes"]` |
| MISSING_LABEL_FILE | 6 ảnh | **người** (`needs_label`) | máy không bịa nhãn, không tạo file rỗng (rỗng = ảnh nền) |
| POSSIBLE_MISSING | 53 issue / 52 ảnh | người | model lớn thấy vật mà nhãn không có: cần mắt người xác nhận |
| POSSIBLE_FALSE_POS | 29 / 27 ảnh | người | box nhãn không khớp dự đoán nào: có thể nhãn thừa, có thể model sót |
| POSSIBLE_LOOSE_BOX | 28 / 24 ảnh | người | cùng vật cùng lớp nhưng IoU < 0.5 |
| POSSIBLE_WRONG_CLASS | 18 / 18 ảnh | người | model nói lớp khác với IoU ≥ 0.5 |
| EMPTY_LABEL | 12 ảnh | người | file rỗng: ảnh nền hay thiếu nhãn? |
| BOX_TINY / BOX_HUGE | 6 dòng / 4 ảnh; 3 / 3 | người | quy tắc dự án, chỉ cảnh báo |
| CLASS_RARE | 4 issue (cấp dataset) | người (theo dõi) | lớp lạ còn sót trước khi sửa; sau cùng `class_stats.csv`: car 101, person 574, truck 41, bus 32 box |

Máy tự sửa **35 thay đổi** (`03_fixes.csv`: 20 `drop_line`, 8 `clip_box`, 6 `needs_label`, 1 `rename_classes`) và mọi thay đổi đều có cột trước → sau. Sau khi sửa (`04_error_list_v2`) chỉ còn 6 ERROR, đều là `MISSING_LABEL_FILE`.

**Vì sao ảnh đầu hàng được ưu tiên.** `05_review_queue.csv` cộng điểm theo `review.weights` × (1 + conf của model). Vì vậy:
- `img_0020` đứng đầu (11,52 điểm), vì vừa bị máy xoá dòng (`FIXED_DROP_LINE`), vừa có cờ `MISSING` và `WRONG_CLASS`.
- Kế tiếp là **6 ảnh `NEEDS_LABEL`** (10 điểm mỗi ảnh). Người không gán thì chúng sẽ chặn Release.
- Sau đó là các ảnh có `WRONG_CLASS`/`MISSING` với conf cao.

Với ngân sách 80 ảnh: trong v2 có **123 cờ ngữ nghĩa (`POSSIBLE_*`) trên 103 ảnh**, người duyệt xem được **94/123 cờ (76%) trên 74/103 ảnh**. Ảnh hạng 80 có 3,343 điểm và ảnh hạng 81 có 3,333 điểm. 45 ảnh không được xem chủ yếu là `LOOSE_BOX` (16) và `FALSE_POS` (11), tức những cờ có trọng số thấp hơn.

## 3. Calibration (2 ngưỡng)
Số đo trên 39 ảnh calib (`submission/calibration/calibration_report.md`; bản chạy với cấu hình khởi đầu được giữ để đối chiếu).

| Tham số | Khởi đầu | Đã chọn | Precision / Recall (trước → sau) | Lý do (đánh đổi) |
|---|---|---|---|---|
| `duplicates.phash_dist` | 2 | **10** | NEAR: 1.00/0.50 (3/6) → 1.00/0.67 (4/6); EXACT giữ 1.00/1.00 | Cờ sai = **xoá nhầm ảnh tốt**, nên ưu tiên precision. Trên calib, các giá trị 4–14 cho kết quả như nhau. Trên raw, số ảnh bị loại là 14 (dist 2), 16 (dist 6), **17 (dist 10–14)**, **26 (dist 16)**, 134 (dist 20). Ba cặp thêm vào khi tăng lên 10 đều là trùng thật (đổi màu, thêm viền, cắt). Chọn 10 để còn cách xa vùng bắt đầu gộp nhầm. |
| `second_opinion.conf` | 0.25 | **0.6** | MISSING 0.50/1.00 → 0.57/1.00; WRONG_CLASS 0.56/0.83 → 0.62/0.83; LOOSE_BOX 0.29/0.40 → 0.20/0.20; FALSE_POS 0.31/1.00 không đổi (dùng `fp_conf`) | Đây là cảnh báo cho người, nên giá của FN (lỗi lọt vào dataset) cao hơn giá của FP (người mở ảnh uổng công). 0.6 là `conf` cao nhất mà recall MISSING vẫn đạt 8/8. Lên 0.7 thì còn 7/8, lên 0.8 còn 6/8. Lên 0.8 thì gate sẽ Release, nhưng là **Release giả** vì checker bị làm mù đi 25%. Đổi lại, số cờ MISSING ở v1 giảm từ 151 (conf 0.25) xuống 53, và hàng đợi giảm từ 143 xuống 125 ảnh. Cái giá phải trả: recall LOOSE_BOX giảm từ 2/5 xuống 1/5. |

**Calibration có thể đánh lừa ở đâu.** Nếu chỉ nhìn bảng sweep thì `phash_dist = 16` là tốt nhất: precision NEAR 1.00, recall 0.83 (5/6), cao hơn mọi giá trị khác. Nhưng trên raw, dist 16 loại thêm 9 ảnh. Mình đã mở xem 6 cặp trong số đó: **5 cặp là ảnh khác hẳn nhau** (img_0011 quần vợt và img_0008 trượt tuyết; img_0013 phòng làm việc và test_087 bóng chày; img_0017, img_0021, img_0177…); chỉ img_0084/img_0074 là trùng thật. Calib có 39 ảnh và chỉ 6 ảnh gần trùng, nên không đủ cặp "khác nhau nhưng phash gần" để lộ ra FP. Precision 1.00 ở đây là do mẫu quá nhỏ, không phải vì ngưỡng an toàn. Mỗi ô chỉ có 5–8 lỗi chèn, nên một lỗi đổi recall 12–20 điểm phần trăm.

## 4. Cửa chặn và điều pipeline KHÔNG bắt được
**(a) Gate chặn đúng.** Mình đã chạy `python -m pipeline.run --budget 0 --reports work/rep_nb --export-dir work/exp_nb --work work/run_nb`. Thêm `--work` để không ghi đè thư mục làm việc của lần chạy chính; mình đã so sha1 các file trong `submission/reports/` trước và sau lần thử, không file nào đổi. Kết quả:
- Không có người duyệt, nên **6 ảnh thiếu file nhãn** vẫn còn nguyên. Vòng sửa thứ hai chỉ ghi lại 6 dòng `needs_label` (`03b_fixes_after_review.csv`) và không tạo file nhãn rỗng.
- Gate kết luận **Rework**, lý do "còn 6 lỗi bắt buộc (ERROR)", **mã thoát 20**.
- Log ghi "KHÔNG xuất: còn lỗi bắt buộc (Rework)" và thư mục `work/exp_nb` **không được tạo ra**.
- Có 112/202 ảnh (55,45%) còn cảnh báo, nhưng gate không cần xét tới vì ERROR được kiểm trước.

**3 lỗi tự nhìn thấy (CP1).** Mình chạy `python scripts/viz_labels.py` trên 10 ảnh raw (img_0001, 0003, 0006, 0014, 0020, 0022, 0030, 0043, 0087, 0127) và mở xem bằng mắt:
1. **img_0001 thiếu box.** Người lính đứng giữa ảnh không có box nào, trong khi người đàn ông bên trái có 2 box gần như trùng nhau (dòng 1 và 3). Pipeline bắt cả hai: `DUP_BOX` dòng 3 (máy xoá) và `POSSIBLE_MISSING`.
2. **img_0020 nhầm lớp.** Chiếc xe buýt "Metro Local" được gán `2 truck` thay vì `3 bus`, và có thêm một box lớp `93`. Pipeline báo `POSSIBLE_WRONG_CLASS` và `BAD_CLASS_ID` dòng 3; ảnh này đứng đầu hàng đợi.
3. **img_0014 box đặt sai chỗ.** Box `person` dòng 2 chủ yếu trùm lên khay ly bia, chỉ chạm mép một người ở rìa trên ảnh; dòng 1 có `nan`. Pipeline báo `BAD_FORMAT` dòng 1 (máy xoá) và `POSSIBLE_MISSING`, **nhưng không báo `POSSIBLE_FALSE_POS` cho box đặt sai**. Ảnh vẫn được người duyệt nhờ cờ khác (hạng 40/125).

**(b) Những gì pipeline không bắt được:**
1. **Ảnh trùng biến đổi mạnh.** Cặp img_0084/img_0074 trên raw (một ảnh bị cắt từ ảnh kia) có phash 16 > 10, nên vẫn nằm trong dataset. Trên calib, calib_037 (mức biến đổi 3) phải tới dist 16 mới bắt được, còn calib_038 (mức 4) **không ngưỡng nào bắt được**. Tăng ngưỡng để bắt các ca này thì lại gộp nhầm ảnh khác nhau (§3).
2. **Box lỏng nhẹ.** Ở conf 0.6, recall LOOSE_BOX trên calib chỉ còn **1/5**. Box nào có IoU với dự đoán ≥ `iou_loose` (0.5) thì được coi là khớp và không bị cờ, dù vẫn rộng hơn vật đáng kể.
3. **Vật mà model lớn cũng sót hoặc cũng nhầm.** MISSING và WRONG_CLASS chỉ có khi yolo26l thấy vật với conf ≥ 0.6 và diện tích ≥ 600 px². Trên calib, 1/6 lỗi WRONG_CLASS không bị cờ. Vật nhỏ hơn 600 px² thì không bao giờ bị cờ MISSING.
4. **Ảnh đã duyệt được coi là sạch.** Trong 80 ảnh đã được thay bằng nhãn người, v3 vẫn còn 29 cảnh báo (11 MISSING, 10 FALSE_POS…). Gate bỏ qua các cảnh báo này vì tin người duyệt; nếu người duyệt sai thì không còn lớp nào kiểm lại.

## 5. Train: raw vs clean (tùy chọn, chấm riêng)
**Cấu hình.**
- Train **trên máy** (NVIDIA RTX 3050 Laptop 4 GB, torch 2.6.0+cu124, ultralytics 8.4.214), không dùng Colab. Lệnh: `python scripts/train_compare.py --variants raw clean --seeds 0 1 --epochs 20`.
- Cả 4 lượt dùng chung `yolo26n.pt`, 20 epoch, imgsz 640, batch 16, val `gold_val` (40 ảnh) và **test 100 ảnh chỉ dùng để đánh giá cuối**.
- `clean` = bản nháp **Hold** `clean_v1` (202 ảnh, `manifest_sha1` 3cb62da…), chưa phải bản phát hành.
- `raw`: JSON ghi 224 ảnh, nhưng Ultralytics tự bỏ **11 ảnh hỏng** (ảnh không đọc được, toạ độ `nan`, lớp 93/7/4, giá trị âm…). Thực tế raw chỉ train trên **213 ảnh**.

Bảng do `scripts/summarize_results.py` sinh (`submission/results/comparison.md`, test 100 ảnh / 387 box):

| biến thể | #ảnh train | số seed | mAP50 | mAP50-95 | precision | recall |
|---|---|---|---|---|---|---|
| raw | 224 (thực train 213) | 2 | 0.725 ± 0.011 | 0.526 ± 0.014 | 0.779 ± 0.092 | 0.609 ± 0.044 |
| clean | 202 | 2 | 0.746 ± 0.007 | 0.520 ± 0.001 | 0.806 ± 0.065 | 0.647 ± 0.045 |

**So chênh lệch với nhiễu giữa seed.**
- mAP50 (clean − raw) = **+0.021**. Con số này khoảng gấp 2 độ lệch chuẩn giữa seed (0.011 ở raw, 0.007 ở clean), và hai khoảng giá trị không chồng nhau: raw 0.717–0.733, clean 0.741–0.751.
- Nhưng **mAP50-95 lại thấp hơn một chút (−0.006)**, nằm trong nhiễu.
- Mỗi biến thể chỉ có 2 seed, nên độ lệch chuẩn ước lượng từ 2 điểm rất không chắc chắn.
- Theo lớp (AP50 trung bình 2 seed): truck 0.622 → 0.668, bus 0.710 → 0.735, person 0.824 → 0.832, car 0.743 → 0.750. Lớp truck lợi nhiều nhất, nhưng AP truck của raw dao động mạnh giữa 2 seed (0.680 và 0.563).
- **Kết luận: clean nhỉnh hơn raw về mAP50 và recall, nhưng bằng chứng còn yếu, chưa đủ để kết luận chắc chắn clean tốt hơn raw.**

**Giả thuyết và cách kiểm:**
1. **Thí nghiệm chủ yếu đo model pretrain, chưa đo chất lượng dữ liệu.** Ở cả 4 lượt, mAP50 trên val cao nhất ở **epoch 1** (raw 0.765/0.792, clean 0.768/0.798), rồi giảm dần còn khoảng 0.58–0.68 ở epoch 20. Vì vậy `best.pt` dùng để đánh giá test gần như là yolo26n pretrain COCO sau 1 epoch, và khác biệt dữ liệu ít có cơ hội thể hiện. *Cách kiểm:* đánh giá `last.pt` của từng lượt trên test, và đo yolo26n pretrain (chưa fine-tune) trên test làm mốc so sánh.
2. **raw có ảnh trùng hoặc rò rỉ test.** Pipeline phát hiện 5 ảnh `LEAK_TEST` (img_0049, 0101, 0167, 0174, 0221 trùng test_033, 039, 044, 085, 009) và 12 ảnh trùng nội bộ. Rò rỉ đáng ra làm **thổi phồng** điểm raw, vậy mà raw vẫn thấp hơn. *Cách kiểm:* đánh giá lại trên test sau khi bỏ 5 ảnh bị rò rỉ, xem khoảng cách giữa hai biến thể thay đổi bao nhiêu.
3. **Phần lợi của clean có thể đến từ 80 ảnh người duyệt hơn là từ máy tự sửa.** Ultralytics đã tự bỏ 11 ảnh hỏng của raw, nên lỗi cú pháp gần như không còn ảnh hưởng. Khác biệt còn lại nằm ở lỗi ngữ nghĩa (thiếu box, nhầm lớp, box lỏng) mà người duyệt đã sửa. *Cách kiểm:* chạy biến thể `auto` (pipeline với `--budget 0 --drop-unlabeled`, không có người duyệt) với cùng 2 seed, rồi so raw / auto / clean.
4. **Test nhỏ** (100 ảnh; truck và bus ít box), nên một vài ảnh có thể làm AP từng lớp dao động mạnh. *Cách kiểm:* thêm seed (≥ 3) và bootstrap trên ảnh test để có khoảng tin cậy.

**Việc tiếp theo:** đánh giá `last.pt` và mốc pretrain, chạy thêm seed 2 và biến thể `auto`. Chỉ khi chênh lệch vẫn lớn hơn nhiễu thì mới kết luận clean tốt hơn.

## 6. Quyết định và ghi chú AI
**(a) Quyết định cuối: Hold.**
- Không có lỗi bắt buộc nào còn lại, nhưng 38/202 ảnh (18,81%) có cảnh báo chưa được duyệt.
- **Điều kiện để thành Release:** người duyệt thêm ít nhất **18 ảnh** trong 38 ảnh này (hàng đợi `05_review_queue.csv` từ hạng 81 trở đi), để còn tối đa 20/202 ảnh (9,9% < 10%), rồi chạy `--resume-after-review`.
- Mình không hạ recall của checker (conf 0.8) hay đổi ngân sách để ép ra Release.
- Kết quả **Rework** chỉ xảy ra khi không có ai gán nhãn cho 6 ảnh thiếu nhãn (§4a).

**(b) Có dùng AI (Claude) để viết 4 module và chạy kiểm tra:**
- **Prompt chính:** mô tả đủ 4 ý (định dạng YOLO `class cx cy w h` kèm dòng mẫu; quy tắc từng module theo docstring; đầu ra `Issue`/log/dict; giới hạn: chỉ sửa 4 module, không ghi `data/raw`, ngưỡng lấy từ `cfg`, không đọc `review_reference`/`test/labels`/`MANIFEST`), yêu cầu đọc docstring và test trước, làm theo thứ tự label_format → gate → autofix → second_opinion.
- **Cách kiểm:**
  - Đọc code xem có xoá hay ghi đè file ngoài dataset làm việc không, có `except: pass` không, có viết cứng ngưỡng không.
  - Chạy test từng module, rồi `pytest -q`: **79 passed**.
  - Thử thêm trên bản sao 3 ca: một dòng dính 2 lỗi (tràn + trùng → chỉ 1 `drop_line`); file có dòng trống xen giữa các dòng lỗi (số dòng gốc 3, 6, 9 đúng); một ảnh có 6 dự đoán chồng nhau (ra đúng WRONG_CLASS, MISSING, LOOSE_BOX, FALSE_POS@6).
  - `git status data/` không có thay đổi, và chạy pipeline 2 lần cho báo cáo giống nhau.
- **Một lần AI sai:**
  - Bản đầu của `gate` so ngưỡng bằng `warn_ratio` **đã làm tròn 4 chữ số**. Test của đề vẫn xanh, nhưng ca biên tự thử 1000 ảnh cảnh báo / 10001 ảnh (9,999%) bị làm tròn thành 0.1 và ra **Hold** sai. Đã sửa thành so bằng tỷ lệ chưa làm tròn, chỉ làm tròn khi in ra.
  - Ngoài ra, khi đọc lại `second_opinion`, mình đổi điều kiện `best_same > 0` thành "có ứng viên cùng lớp hay không", vì nếu `iou_missing = 0` thì một ứng viên có IoU = 0 sẽ bị bỏ sót. Lỗi này tìm thấy khi đọc code, không phải do test làm lộ ra.
