import cv2
import numpy as np

import constants as c


def crop_dial(img, x1, y1, x2, y2):
    return cv2.resize(img[int(y1):int(y2), int(x1):int(x2)], None,
                       fx=c.CROP_UPSCALE_FACTOR, fy=c.CROP_UPSCALE_FACTOR,
                       interpolation=cv2.INTER_CUBIC)


def ocr_digits(crop, reader, min_conf=c.OCR_MIN_CONF):
    numbers = {}
    for bbox, text, conf in reader.readtext(crop, allowlist=c.OCR_ALLOWLIST, mag_ratio=c.OCR_MAG_RATIO):
        if not text.isdigit():
            continue
        if conf < min_conf:
            continue
        val = int(text)
        if not (1 <= val <= 12):
            continue
        pts = np.array(bbox, dtype=np.float64)
        numbers[val] = {"val": val, "box": pts.astype(int),
                         "cx": pts[:, 0].mean(), "cy": pts[:, 1].mean(), "conf": conf}
    return numbers


def line_intersection(p1, p2, p3, p4):
    d1 = (p2[0] - p1[0], p2[1] - p1[1])
    d2 = (p4[0] - p3[0], p4[1] - p3[1])
    det = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(det) < 1e-9:
        return None
    t = ((p3[0] - p1[0]) * d2[1] - (p3[1] - p1[1]) * d2[0]) / det
    return (p1[0] + t * d1[0], p1[1] + t * d1[1])


def find_center(numbers, w, h):
    pairs = []
    for a, b in ((1, 7), (2, 8), (3, 9), (4, 10), (5, 11), (6, 12)):
        if a in numbers and b in numbers:
            pairs.append((a, b))

    lines = [((numbers[a]["cx"], numbers[a]["cy"]), (numbers[b]["cx"], numbers[b]["cy"]))
             for a, b in pairs]

    pts = []
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            p = line_intersection(lines[i][0], lines[i][1], lines[j][0], lines[j][1])
            if p is not None and 0 <= p[0] < w and 0 <= p[1] < h:
                pts.append(p)

    if not pts:
        return w / 2.0, h / 2.0, pairs

    arr = np.array(pts)
    return float(np.median(arr[:, 0])), float(np.median(arr[:, 1])), pairs


def hands_mask(crop, cx, cy, R, numbers, strength):
    h, w = crop.shape[:2]
    gray = cv2.medianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 5)

    yy, xx = np.mgrid[0:h, 0:w]
    dist = np.hypot(xx - cx, yy - cy)
    dial = dist < c.DIAL_MASK_RADIUS_MARGIN * R

    thr, _ = cv2.threshold(gray[dial].astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    darker = np.median(gray[dial]) > thr
    shift = strength * c.HAND_MASK_MAX_THRESHOLD_SHIFT
    eff_thr = thr - shift if darker else thr + shift
    bw = ((gray < eff_thr) if darker else (gray > eff_thr)).astype(np.uint8) * 255
    bw[~dial] = 0
    bw = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones(c.HAND_MASK_CLOSE_KERNEL_SIZE, np.uint8))

    num_mask = np.zeros((h, w), np.uint8)
    for n in numbers.values():
        cv2.fillPoly(num_mask, [n["box"].astype(np.int32)], 255)
    bw[cv2.dilate(num_mask, np.ones(c.HAND_MASK_NUMBER_DILATE_KERNEL_SIZE, np.uint8)) > 0] = 0

    open_k = max(3, int(round((c.HAND_MASK_OPEN_KERNEL_BASE_RATIO +
                                c.HAND_MASK_OPEN_KERNEL_STRENGTH_RATIO * strength) * R)) | 1)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (open_k, open_k))
    bw = cv2.morphologyEx(bw, cv2.MORPH_OPEN, kernel)
    bw = cv2.dilate(bw, kernel, iterations=c.HAND_MASK_DILATE_ITERATIONS)

    n_lbl, lbl = cv2.connectedComponents(bw)
    center_lbls = set(np.unique(lbl[dist < c.HAND_MASK_CENTER_RADIUS_RATIO * R])) - {0}
    if center_lbls:
        bw = np.where(np.isin(lbl, list(center_lbls)), 255, 0).astype(np.uint8)
    return bw


def hough_candidates(bw, cx, cy, R, crop_size):
    lines = cv2.HoughLinesP(bw, c.HOUGH_RHO, np.pi / c.HOUGH_THETA_DIVISOR, threshold=c.HOUGH_THRESHOLD,
                             minLineLength=max(5, int(c.HOUGH_MIN_LINE_LENGTH_RATIO * R)),
                             maxLineGap=max(2, int(c.HOUGH_MAX_LINE_GAP_RATIO * R)))
    if lines is None:
        return []

    min_len = c.HOUGH_MIN_LENGTH_CROP_RATIO * crop_size
    out = []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        d1, d2 = np.hypot(x1 - cx, y1 - cy), np.hypot(x2 - cx, y2 - cy)
        length, ex, ey = (d1, x1, y1) if d1 >= d2 else (d2, x2, y2)
        if length < min_len:
            continue
        angle = np.degrees(np.arctan2(ey - cy, ex - cx)) % 360.0
        out.append({"angle": angle, "length": float(length)})
    return sorted(out, key=lambda c_: -c_["length"])


def dedup_hands(candidates):
    accepted = []
    for cand in candidates:
        dup = False
        for a in accepted:
            same_dir = abs((cand["angle"] - a["angle"] + 180.0) % 360.0 - 180.0) <= c.DEDUP_SAME_DIRECTION_TOLERANCE_DEG
            d = abs((cand["angle"] - a["angle"]) % 180.0)
            same_arm = (cand["length"] < c.DEDUP_SAME_ARM_LENGTH_RATIO * a["length"] and
                        min(d, 180.0 - d) <= c.DEDUP_SAME_ARM_TOLERANCE_DEG)
            if same_dir or same_arm:
                dup = True
                break
        if not dup:
            accepted.append(cand)
            if len(accepted) == c.DEDUP_MAX_HANDS:
                break
    return accepted


def dial_otsu(gray, cx, cy, R):
    h, w = gray.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    dial = np.hypot(xx - cx, yy - cy) < c.DIAL_MASK_RADIUS_MARGIN * R
    thr, _ = cv2.threshold(gray[dial].astype(np.uint8), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    darker = np.median(gray[dial]) > thr
    return thr, darker


def ray_darkness_length(gray, cx, cy, angle, max_r, thr, darker,
                         patch=c.RAY_PATCH_RADIUS, perp_tol=c.RAY_PERPENDICULAR_TOLERANCE,
                         gap_tol=c.RAY_GAP_TOLERANCE):
    h, w = gray.shape[:2]
    a = np.radians(angle)
    dx, dy = np.cos(a), np.sin(a)
    ppx, ppy = -dy, dx
    last_hit, gap = 0.0, 0
    r = 0.0
    while r <= max_r:
        hit = False
        for off in range(-perp_tol, perp_tol + 1):
            x = int(round(cx + r * dx + off * ppx))
            y = int(round(cy + r * dy + off * ppy))
            x0, x1 = max(0, x - patch), min(w, x + patch + 1)
            y0, y1 = max(0, y - patch), min(h, y + patch + 1)
            if x1 > x0 and y1 > y0:
                val = gray[y0:y1, x0:x1].mean()
                if (val < thr) if darker else (val > thr):
                    hit = True
                    break
        if hit:
            last_hit, gap = r, 0
        else:
            gap += 1
            if gap > gap_tol and last_hit > 0:
                break
        r += 1.0
    return last_hit


def clock_time(hands):
    if not hands:
        return None
    minute_hand = hands[0]
    hour_hand = hands[1] if len(hands) >= 2 else hands[0]

    minute = ((minute_hand["angle"] - 270.0) % 360.0) / 6.0 % 60.0
    hour_f = ((hour_hand["angle"] - 270.0) % 360.0) / 30.0 % 12.0
    hour = int(hour_f)

    frac, exp = hour_f - hour, minute / 60.0
    if frac < c.CLOCK_HOUR_CARRY_FRACTION_LOW and exp > c.CLOCK_HOUR_CARRY_FRACTION_HIGH:
        hour = (hour - 1) % 12
    elif frac > c.CLOCK_HOUR_CARRY_FRACTION_HIGH and exp < c.CLOCK_HOUR_CARRY_FRACTION_LOW:
        hour = (hour + 1) % 12
    hour = 12 if hour == 0 else hour
    return hour, minute


def draw_overlay(crop, cx, cy, R, numbers, pairs, bw, hands):
    vis = crop.copy()
    overlay = vis.copy()
    overlay[bw > 0] = c.COLOR_MASK_OVERLAY
    vis = cv2.addWeighted(overlay, c.MASK_OVERLAY_ALPHA, vis, c.MASK_BASE_ALPHA, 0)

    for val, n in numbers.items():
        cv2.polylines(vis, [n["box"]], True, c.COLOR_NUMBER_BOX, c.NUMBER_BOX_THICKNESS)
        bx, by = n["box"][0]
        cv2.putText(vis, f"{val} ({n['conf']:.2f})", (bx, by - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, c.NUMBER_TEXT_SCALE, c.COLOR_NUMBER_TEXT, c.NUMBER_TEXT_THICKNESS)

    for a, b in pairs:
        p1 = (int(numbers[a]["cx"]), int(numbers[a]["cy"]))
        p2 = (int(numbers[b]["cx"]), int(numbers[b]["cy"]))
        cv2.line(vis, p1, p2, c.COLOR_PAIR_LINE, c.PAIR_LINE_THICKNESS)

    cv2.circle(vis, (int(cx), int(cy)), int(R), c.COLOR_DIAL_CIRCLE, c.DIAL_CIRCLE_THICKNESS)

    hand_colors = {0: c.COLOR_MINUTE_HAND, 1: c.COLOR_HOUR_HAND}
    for i, g in enumerate(hands[:2]):
        label, color = c.HAND_LABELS[i], hand_colors[i]
        a = np.radians(g["angle"])
        ex, ey = int(cx + g["length"] * np.cos(a)), int(cy + g["length"] * np.sin(a))
        cv2.line(vis, (int(cx), int(cy)), (ex, ey), color, c.HAND_LINE_THICKNESS)
        cv2.putText(vis, label, (ex + 6, ey), cv2.FONT_HERSHEY_SIMPLEX, c.HAND_LABEL_SCALE, color, c.HAND_LABEL_THICKNESS)

    cv2.circle(vis, (int(cx), int(cy)), c.CENTER_DOT_RADIUS, c.COLOR_CENTER_DOT, -1)
    return vis


def read_clock(img, model, reader):
    boxes = model(img, classes=[0], verbose=False)[0].boxes
    if len(boxes) == 0:
        return None, None

    x1, y1, x2, y2 = map(float, boxes[0].xyxy[0])
    crop = crop_dial(img, x1, y1, x2, y2)
    h, w = crop.shape[:2]

    numbers = ocr_digits(crop, reader)
    cx, cy, pairs = find_center(numbers, w, h)
    R = c.DIAL_RADIUS_RATIO * min(w, h)

    bw, hands = None, []
    for strength in c.HAND_MASK_STRENGTHS:
        bw = hands_mask(crop, cx, cy, R, numbers, strength)
        cands = hough_candidates(bw, cx, cy, R, min(w, h))
        hands = dedup_hands(cands)
        if len(hands) >= 2:
            break

    gray = cv2.medianBlur(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 5)
    thr, darker = dial_otsu(gray, cx, cy, R)
    max_r = c.RAY_MAX_RADIUS_RATIO * min(w, h)
    for hd in hands:
        hd["length"] = ray_darkness_length(gray, cx, cy, hd["angle"], max_r, thr, darker)
    hands.sort(key=lambda hd: -hd["length"])

    time = clock_time(hands)
    vis = draw_overlay(crop, cx, cy, R, numbers, pairs, bw, hands)
    return time, vis
