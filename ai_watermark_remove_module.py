
import os
import threading
import subprocess
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

import ttkbootstrap as tb
from ttkbootstrap.constants import *
from PIL import Image, ImageTk, ImageDraw, ImageFilter, ImageChops

try:
    import cv2
    import numpy as np
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

try:
    import requests
    HAS_REQUESTS = True
except Exception:
    HAS_REQUESTS = False

# ── 本地深度学习后端检测 ──────────────────────────────────────────────
HAS_TORCH = False
HAS_CUDA  = False
TORCH_DEVICE = "cpu"

try:
    import torch
    import torch.nn.functional as F
    HAS_TORCH = True
    HAS_CUDA  = torch.cuda.is_available()
    TORCH_DEVICE = "cuda" if HAS_CUDA else "cpu"
except Exception:
    pass

HAS_NVIDIA_GPU = False
try:
    _nvidia_probe = subprocess.run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        capture_output=True,
        text=True,
        timeout=2,
        check=False,
    )
    HAS_NVIDIA_GPU = _nvidia_probe.returncode == 0 and bool(_nvidia_probe.stdout.strip())
except Exception:
    HAS_NVIDIA_GPU = False

from common_utils import (
    create_input_row, create_output_row, default_output_dir,
    make_card, make_primary_button, make_secondary_button,
    open_image_with_exif, save_image_by_format, list_images, DATA_DIR,
    bind_drop_to_widget
)

import io
import base64
import json

_BRUSH_COLORS = {"paint": "#ff3232", "erase": "#4488ff"}


# ─────────────────────────────────────────────
#  API Key 持久化
# ─────────────────────────────────────────────

_API_KEY_FILE = DATA_DIR / "anthropic_api_key.json"

def _load_api_key():
    try:
        if _API_KEY_FILE.exists():
            return json.loads(_API_KEY_FILE.read_text(encoding="utf-8")).get("api_key", "")
    except Exception:
        pass
    return ""

def _save_api_key(key):
    try:
        _API_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _API_KEY_FILE.write_text(json.dumps({"api_key": key}, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def _get_api_key():
    """优先读环境变量，其次读本地配置文件"""
    return os.environ.get("ANTHROPIC_API_KEY", "") or _load_api_key()


# ─────────────────────────────────────────────
#  Anthropic API inpainting helper
# ─────────────────────────────────────────────

def _pil_to_base64(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return base64.b64encode(buf.getvalue()).decode()


def _get_mask_bbox(mask, w, h, pad=60):
    """获取蒙版的边界框，带padding"""
    if HAS_CV2:
        arr = np.array(mask)
        ys, xs = np.where(arr > 30)
        if len(xs) == 0:
            return None
        return (
            max(0, int(xs.min()) - pad),
            max(0, int(ys.min()) - pad),
            min(w, int(xs.max()) + pad),
            min(h, int(ys.max()) + pad),
        )
    data = list(mask.getdata())
    xs, ys = [], []
    for idx, v in enumerate(data):
        if v > 30:
            xs.append(idx % w)
            ys.append(idx // w)
    if not xs:
        return None
    return (max(0, min(xs)-pad), max(0, min(ys)-pad),
            min(w, max(xs)+pad), min(h, max(ys)+pad))


# ─────────────────────────────────────────────────────────────────────
#  本地深度修复引擎
#  Priority: flat background fill > CUDA generative fill > torch frequency > OpenCV
# ─────────────────────────────────────────────────────────────────────

# -----------------------------------------------------------------------------
#  Local generative inpaint engine
#  Priority: flat background fill > CUDA contextual synthesis > torch frequency > OpenCV
# -----------------------------------------------------------------------------

def _crop_inpaint_roi(orig_rgb, mask, strength=7, pad=None):
    pad = pad or max(72, strength * 14)
    bbox = _get_mask_bbox(mask, orig_rgb.width, orig_rgb.height, pad=pad)
    if bbox is None:
        return orig_rgb, mask, (0, 0, orig_rgb.width, orig_rgb.height)
    left, top, right, bottom = bbox
    return orig_rgb.crop((left, top, right, bottom)), mask.crop((left, top, right, bottom)), bbox


def _resize_for_local_model(img, mask, limit):
    w, h = img.size
    longest = max(w, h)
    if longest <= limit:
        return img, mask, 1.0
    scale = limit / float(longest)
    size = (max(32, int(round(w * scale))), max(32, int(round(h * scale))))
    return (
        img.resize(size, Image.Resampling.LANCZOS),
        mask.resize(size, Image.Resampling.NEAREST),
        scale,
    )


def _torch_dilate_bool(mask_t, kernel_size=3):
    kernel = torch.ones((1, 1, kernel_size, kernel_size), device=mask_t.device)
    value = F.conv2d(mask_t.float().unsqueeze(0).unsqueeze(0), kernel, padding=kernel_size // 2)
    return value[0, 0] > 0


def _sample_source_indices(indexes, max_samples):
    if indexes.numel() <= max_samples:
        return indexes
    positions = torch.linspace(0, indexes.numel() - 1, steps=max_samples, device=indexes.device)
    return indexes[positions.round().long()]


def _contextual_fill_band(result_t, known_t, band_t, patch=9, topk=4, max_source=4096):
    channels, height, width = result_t.shape
    radius = patch // 2
    patch_area = patch * patch
    center = patch_area // 2
    center_offsets = torch.tensor(
        [c * patch_area + center for c in range(channels)],
        device=result_t.device,
        dtype=torch.long,
    )

    padded_img = F.pad(result_t.unsqueeze(0), (radius, radius, radius, radius), mode='reflect')
    img_patches = F.unfold(padded_img, kernel_size=patch).squeeze(0).transpose(0, 1).contiguous()

    padded_known = F.pad(known_t.float().unsqueeze(0).unsqueeze(0), (radius, radius, radius, radius), mode='reflect')
    known_patches = F.unfold(padded_known, kernel_size=patch).squeeze(0).transpose(0, 1).contiguous()

    source_idx = torch.nonzero(known_patches.min(dim=1).values > 0.999, as_tuple=False).squeeze(1)
    if source_idx.numel() == 0:
        return None

    source_idx = _sample_source_indices(source_idx, max_source)
    source_patches = img_patches[source_idx]
    source_centers = source_patches[:, center_offsets]

    target_idx = torch.nonzero(band_t.reshape(-1), as_tuple=False).squeeze(1)
    if target_idx.numel() == 0:
        return None

    predictions = torch.zeros((target_idx.numel(), channels), device=result_t.device, dtype=result_t.dtype)
    batch_size = 24 if result_t.is_cuda else 8

    for start in range(0, target_idx.numel(), batch_size):
        idx_batch = target_idx[start:start + batch_size]
        target_patches = img_patches[idx_batch]
        visible = known_patches[idx_batch].repeat_interleave(channels, dim=1)
        visible_sum = visible.sum(dim=1, keepdim=True)
        weak_context = visible_sum.squeeze(1) < max(9, patch)

        diff = source_patches.unsqueeze(0) - target_patches.unsqueeze(1)
        dist = ((diff * visible.unsqueeze(1)) ** 2).sum(dim=2) / visible_sum.clamp_min(1.0)

        k = min(topk, source_patches.shape[0])
        values, indices = torch.topk(dist, k=k, dim=1, largest=False)
        weights = torch.softmax(-values * 8.0, dim=1)
        colors = source_centers[indices]
        pred = (colors * weights.unsqueeze(-1)).sum(dim=1)

        if weak_context.any():
            original_colors = result_t[:, idx_batch // width, idx_batch % width].transpose(0, 1)
            pred[weak_context] = original_colors[weak_context]

        predictions[start:start + idx_batch.numel()] = pred

    return target_idx, predictions


def _torch_generative_inpaint(orig_rgb, mask, strength=7, progress_cb=None):
    if not HAS_TORCH or not HAS_CV2:
        return None

    try:
        roi_img, roi_mask, bbox = _crop_inpaint_roi(orig_rgb, mask, strength)
        limit = 896 if HAS_CUDA else 512
        work_img, work_mask, scale = _resize_for_local_model(roi_img, roi_mask, limit=limit)

        if progress_cb:
            device_name = 'CUDA' if HAS_CUDA else 'CPU'
            progress_cb(f'生成式填充初始化中（{device_name}）…')

        init_result = _classical_inpaint(work_img, work_mask, strength)
        img_arr = np.array(work_img.convert('RGB')).astype(np.float32) / 255.0
        init_arr = np.array(init_result.convert('RGB')).astype(np.float32) / 255.0
        mask_arr = np.array(work_mask)
        _, mask_bin = cv2.threshold(mask_arr, 30, 255, cv2.THRESH_BINARY)

        result_t = torch.from_numpy(init_arr).permute(2, 0, 1).to(TORCH_DEVICE)
        known_t = torch.from_numpy(mask_bin == 0).to(TORCH_DEVICE)
        missing_t = ~known_t

        patch = min(13, max(7, strength + 4))
        if patch % 2 == 0:
            patch += 1

        passes = 8 if HAS_CUDA else 4
        max_source = 6144 if HAS_CUDA else 2048

        for step in range(passes):
            if not bool(missing_t.any()):
                break

            band_t = missing_t & _torch_dilate_bool(known_t, kernel_size=3)
            if not bool(band_t.any()):
                band_t = missing_t

            filled = _contextual_fill_band(
                result_t=result_t,
                known_t=known_t,
                band_t=band_t,
                patch=patch,
                topk=4 if HAS_CUDA else 3,
                max_source=max_source,
            )
            if filled is None:
                break

            target_idx, colors = filled
            ys = torch.div(target_idx, result_t.shape[2], rounding_mode='floor')
            xs = target_idx % result_t.shape[2]
            result_t[:, ys, xs] = colors.transpose(0, 1)
            known_t[ys, xs] = True
            missing_t[ys, xs] = False

            if progress_cb:
                progress_cb(f'生成式填充采样中（{step + 1}/{passes}）…')

        result_np = result_t.permute(1, 2, 0).detach().cpu().numpy()
        result_np = (np.clip(result_np, 0, 1) * 255).astype(np.uint8)
        result_img = Image.fromarray(result_np)
        result_img = _color_align(work_img, result_img, work_mask)

        if scale != 1.0:
            result_img = result_img.resize(roi_img.size, Image.Resampling.LANCZOS)

        output = orig_rgb.copy()
        output.paste(result_img, box=(bbox[0], bbox[1]))
        return output

    except Exception as e:
        if progress_cb:
            progress_cb(f'生成式填充异常({str(e)[:40]})，降级处理中…')
        return None


def _torch_frequency_inpaint(orig_rgb, mask, strength=7, progress_cb=None):
    """
    基于 PyTorch 的频域修复：
    1. 对修复区域做傅里叶变换
    2. 用周边频率成分填充被遮挡区域
    3. 逆变换恢复空间域图像
    支持 CUDA 加速。
    """
    if not HAS_TORCH or not HAS_CV2:
        return None
    try:
        if progress_cb:
            dev = "CUDA" if HAS_CUDA else "CPU"
            progress_cb(f"PyTorch 频域修复中（{dev}）…")

        img_arr = np.array(orig_rgb.convert("RGB")).astype(np.float32) / 255.0
        msk_arr = np.array(mask).astype(np.float32) / 255.0
        _, msk_bin_np = cv2.threshold(np.array(mask), 30, 255, cv2.THRESH_BINARY)

        # 膨胀蒙版
        kernel = np.ones((7, 7), np.uint8)
        msk_dilated = cv2.dilate(msk_bin_np, kernel, iterations=3).astype(np.float32) / 255.0

        # 转为 torch tensor
        img_t = torch.from_numpy(img_arr).permute(2, 0, 1).unsqueeze(0).to(TORCH_DEVICE)  # 1,3,H,W
        msk_t = torch.from_numpy(msk_dilated).unsqueeze(0).unsqueeze(0).to(TORCH_DEVICE)  # 1,1,H,W

        # ── 先做经典修复作为初始值 ──
        init_result = _classical_inpaint(orig_rgb, mask, strength)
        init_arr = np.array(init_result).astype(np.float32) / 255.0
        init_t = torch.from_numpy(init_arr).permute(2, 0, 1).unsqueeze(0).to(TORCH_DEVICE)

        # ── 频域优化：最小化修复区域与周边频率的差异 ──
        result_t = init_t.clone().requires_grad_(False)

        # 对每个通道做频域平滑
        channels = []
        for c in range(3):
            ch_orig = img_t[0, c]       # H,W
            ch_init = init_t[0, c]
            ch_msk  = msk_t[0, 0]

            # FFT
            fft_orig = torch.fft.fft2(ch_orig)
            fft_init = torch.fft.fft2(ch_init)

            # 在频域中：蒙版外用原始频率，蒙版内插值
            # 低频成分（背景纹理）从原图取，高频（细节）从init取
            H, W = ch_orig.shape
            cy, cx = H // 2, W // 2
            low_r = min(cy, cx) // 3

            # 创建低频 mask（频域中心区域）
            yy = torch.arange(H, device=TORCH_DEVICE).float() - cy
            xx = torch.arange(W, device=TORCH_DEVICE).float() - cx
            yy, xx = torch.meshgrid(yy, xx, indexing='ij')
            freq_dist = torch.sqrt(yy**2 + xx**2)
            low_freq_mask = (freq_dist < low_r).float()

            # shift
            fft_orig_s = torch.fft.fftshift(fft_orig)
            fft_init_s = torch.fft.fftshift(fft_init)

            # 融合：低频用原始，高频用init
            fft_blend = fft_orig_s * low_freq_mask + fft_init_s * (1 - low_freq_mask)
            fft_blend_us = torch.fft.ifftshift(fft_blend)
            ch_result = torch.fft.ifft2(fft_blend_us).real
            ch_result = torch.clamp(ch_result, 0, 1)

            # 只在蒙版区域用频域结果，其余保持原图
            ch_final = ch_orig * (1 - ch_msk) + ch_result * ch_msk
            channels.append(ch_final)

        result_t = torch.stack(channels, dim=0).unsqueeze(0)  # 1,3,H,W

        # 转回 PIL
        result_np = result_t[0].permute(1, 2, 0).cpu().numpy()
        result_np = (np.clip(result_np, 0, 1) * 255).astype(np.uint8)
        result_pil = Image.fromarray(result_np)

        # 最终色调对齐
        result_pil = _color_align(orig_rgb, result_pil, mask)

        if progress_cb:
            progress_cb("频域修复完成，正在边缘融合…")

        return result_pil

    except Exception as e:
        if progress_cb:
            progress_cb(f"频域修复异常({str(e)[:30]})，降级…")
        return None


def _color_align(orig_rgb, repaired, mask):
    """
    对修复区域做色调统计对齐：
    采样蒙版周边的原图像素，把修复结果的颜色均值/方差对齐过去。
    """
    if not HAS_CV2:
        return repaired
    try:
        orig_arr    = np.array(orig_rgb).astype(np.float32)
        repair_arr  = np.array(repaired).astype(np.float32)
        msk_arr     = np.array(mask)
        _, msk_bin  = cv2.threshold(msk_arr, 30, 255, cv2.THRESH_BINARY)

        # 采样周边区域
        kernel  = np.ones((30, 30), np.uint8)
        dilated = cv2.dilate(msk_bin, kernel, iterations=1)
        border  = (dilated > 0) & (msk_bin == 0)

        if border.sum() < 20:
            return repaired

        b_orig   = orig_arr[border]
        b_repair = repair_arr[border]

        orig_mean   = b_orig.mean(axis=0)
        repair_mean = b_repair.mean(axis=0)
        orig_std    = b_orig.std(axis=0)   + 1e-6
        repair_std  = b_repair.std(axis=0) + 1e-6

        zone = msk_bin > 0
        if zone.sum() == 0:
            return repaired

        pixels = repair_arr[zone]
        # 均值+方差对齐（保守系数避免过度矫正）
        corrected = (pixels - repair_mean) * np.clip(orig_std / repair_std, 0.6, 1.6) * 0.5 \
                    + repair_mean + (orig_mean - repair_mean) * 0.65
        corrected = np.clip(corrected, 0, 255)
        repair_arr[zone] = corrected

        # 边缘羽化
        dist      = cv2.distanceTransform(msk_bin, cv2.DIST_L2, 5)
        feather_k = np.ones((11, 11), np.uint8)
        outer     = cv2.dilate(msk_bin, feather_k, iterations=2)
        outer_dist= cv2.distanceTransform(outer, cv2.DIST_L2, 5)
        weight    = np.zeros_like(dist, dtype=np.float32)
        valid     = outer > 0
        weight[valid] = np.clip(dist[valid] / (outer_dist[valid] + 1e-6), 0, 1)
        w3 = weight[:, :, np.newaxis]

        final = (repair_arr * w3 + orig_arr * (1 - w3)).astype(np.uint8)
        # 只对覆盖区域写入
        out = orig_arr.copy().astype(np.uint8)
        out[outer > 0] = final[outer > 0]
        return Image.fromarray(out)
    except Exception:
        return repaired



def _refine_text_watermark_mask(orig_rgb, mask, strength=7):
    """Expand hand-painted mask to better cover bright semi-transparent watermark strokes."""
    if not HAS_CV2:
        return mask

    try:
        img = cv2.cvtColor(np.array(orig_rgb.convert("RGB")), cv2.COLOR_RGB2BGR)
        mask_arr = np.array(mask)
        _, base = cv2.threshold(mask_arr, 30, 255, cv2.THRESH_BINARY)
        if base.max() == 0:
            return mask

        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        # Bright, low-saturation pixels are common for white watermark text/logos.
        bright = cv2.inRange(hsv, (0, 0, 150), (180, 90, 255))
        bright = cv2.medianBlur(bright, 3)

        # Keep only candidates near the user's painted area.
        near = cv2.dilate(base, np.ones((max(5, strength * 2 + 1), max(5, strength * 2 + 1)), np.uint8), iterations=2)
        candidate = cv2.bitwise_and(bright, near)

        # Pull in thin anti-aliased edges that often remain after text removal.
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        edge = cv2.threshold(grad, 14, 255, cv2.THRESH_BINARY)[1]
        edge = cv2.bitwise_and(edge, near)
        candidate = cv2.bitwise_or(candidate, edge)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
        filtered = np.zeros_like(candidate)
        dilated_base = cv2.dilate(base, np.ones((5, 5), np.uint8), iterations=1)
        for label in range(1, num_labels):
            x, y, w, h, area = stats[label]
            if area < 6 or area > max(6000, base.sum() // 255 * 12):
                continue
            comp = (labels == label).astype(np.uint8) * 255
            overlap = cv2.bitwise_and(comp, dilated_base)
            if overlap.max() > 0:
                filtered = cv2.bitwise_or(filtered, comp)

        refined = cv2.bitwise_or(base, filtered)
        refined = cv2.morphologyEx(refined, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        refined = cv2.dilate(refined, np.ones((3, 3), np.uint8), iterations=max(1, strength // 4))
        return Image.fromarray(refined)
    except Exception:
        return mask


def _post_blend_inpaint(orig_rgb, repaired, mask, feather=5):
    """Blend repaired region back with a feathered alpha to reduce residual seams/ghosting."""
    if not HAS_CV2:
        return repaired

    try:
        orig = np.array(orig_rgb.convert("RGB")).astype(np.float32)
        rep = np.array(repaired.convert("RGB")).astype(np.float32)
        m = np.array(mask)
        _, m = cv2.threshold(m, 30, 255, cv2.THRESH_BINARY)
        m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=1)
        blur_size = max(3, feather * 2 + 1)
        alpha = cv2.GaussianBlur(m, (blur_size, blur_size), 0).astype(np.float32) / 255.0
        alpha = alpha[:, :, None]
        out = rep * alpha + orig * (1.0 - alpha)
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    except Exception:
        return repaired


def _recover_white_overlay(orig_rgb, repaired, mask):
    """Try to reverse a semi-transparent white watermark instead of fully hallucinating it away."""
    if not HAS_CV2:
        return repaired

    try:
        orig = np.array(orig_rgb.convert("RGB")).astype(np.float32)
        base = np.array(repaired.convert("RGB")).astype(np.float32)
        m = np.array(mask)
        _, m = cv2.threshold(m, 30, 255, cv2.THRESH_BINARY)
        if m.max() == 0:
            return repaired

        # Assume the watermark color is close to white and solve a soft alpha matte.
        denom = np.clip(255.0 - base, 8.0, 255.0)
        alpha = np.max((orig - base) / denom, axis=2)
        alpha = np.clip(alpha, 0.0, 0.82)

        luma_orig = cv2.cvtColor(orig.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        luma_base = cv2.cvtColor(base.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float32)
        boost = (luma_orig > luma_base + 8).astype(np.float32)
        alpha *= boost * (m.astype(np.float32) / 255.0)

        alpha = cv2.GaussianBlur(alpha, (5, 5), 0)
        alpha = np.clip(alpha, 0.0, 0.82)[:, :, None]

        recovered = (orig - alpha * 255.0) / np.clip(1.0 - alpha, 0.18, 1.0)
        recovered = np.clip(recovered, 0, 255)

        # Use recovered pixels only where a meaningful white overlay was detected.
        use_recovered = (alpha[:, :, 0] > 0.06)[:, :, None]
        out = np.where(use_recovered, recovered, base)
        return Image.fromarray(out.astype(np.uint8))
    except Exception:
        return repaired


def _detect_overlay_text_mask(orig_rgb, base_mask, strength=7):
    """Detect small bright overlay text/logo candidates in the top/bottom bands."""
    if not HAS_CV2:
        return base_mask

    try:
        rgb = np.array(orig_rgb.convert("RGB"))
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        base = np.array(base_mask)
        _, base_bin = cv2.threshold(base, 30, 255, cv2.THRESH_BINARY)

        h, w = gray.shape
        band_h = max(40, int(h * 0.24))
        roi = np.zeros((h, w), dtype=np.uint8)
        roi[:band_h, :] = 255
        roi[h - band_h:, :] = 255

        # White/light overlay text tends to have low saturation and high value.
        bright = cv2.inRange(hsv, (0, 0, 155), (180, 120, 255))

        # Semi-transparent strokes also create local contrast against the background.
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        edge = cv2.threshold(grad, 18, 255, cv2.THRESH_BINARY)[1]

        candidate = cv2.bitwise_and(bright, roi)
        candidate = cv2.bitwise_or(candidate, cv2.bitwise_and(edge, candidate))
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8), iterations=1)
        candidate = cv2.dilate(candidate, np.ones((3, 3), np.uint8), iterations=1)

        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(candidate, 8)
        keep = np.zeros_like(candidate)
        near_user = cv2.dilate(base_bin, np.ones((max(5, strength * 5), max(5, strength * 5)), np.uint8), iterations=1)
        center_y1, center_y2 = int(h * 0.26), int(h * 0.78)

        for label in range(1, num_labels):
            x, y, cw, ch, area = stats[label]
            if area < 18:
                continue
            if ch > int(h * 0.09):
                continue
            if cw > int(w * 0.55):
                continue
            if center_y1 < y < center_y2:
                continue

            comp = (labels == label).astype(np.uint8) * 255
            overlaps_user = cv2.bitwise_and(comp, near_user).max() > 0

            # Keep small top/bottom text automatically; larger regions still require user guidance.
            if overlaps_user or (area < int(h * w * 0.012) and ch < int(h * 0.07)):
                keep = cv2.bitwise_or(keep, comp)

        # Merge nearby glyphs into text lines while keeping them reasonably thin.
        keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8), iterations=1)
        keep = cv2.bitwise_or(keep, base_bin)
        return Image.fromarray(keep)
    except Exception:
        return base_mask

def _detect_painted_doubao_mask(orig_rgb, base_mask, strength=7):
    """Refine only inside the user's painted bbox for semi-transparent corner text like '豆包AI生成'."""
    if not HAS_CV2:
        return base_mask

    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(base_mask, w, h, pad=max(6, strength * 2))
        if bbox is None:
            return base_mask
        x1, y1, x2, y2 = bbox

        rgb = np.array(orig_rgb.convert("RGB"))
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        base = np.array(base_mask)
        _, base_bin = cv2.threshold(base, 30, 255, cv2.THRESH_BINARY)

        roi = np.zeros((h, w), dtype=np.uint8)
        roi[y1:y2, x1:x2] = 255

        bright = cv2.inRange(hsv, (0, 0, 140), (180, 150, 255))
        edge = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        edge = cv2.threshold(edge, 10, 255, cv2.THRESH_BINARY)[1]

        cand = cv2.bitwise_and(bright, roi)
        cand = cv2.bitwise_or(cand, cv2.bitwise_and(edge, roi))
        cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
        cand = cv2.dilate(cand, np.ones((3, 3), np.uint8), iterations=1)

        near = cv2.dilate(base_bin, np.ones((max(3, strength * 2 + 1), max(3, strength * 2 + 1)), np.uint8), iterations=1)
        keep = cv2.bitwise_and(cand, near)
        keep = cv2.bitwise_or(keep, base_bin)
        keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((3, 5), np.uint8), iterations=1)
        return Image.fromarray(keep)
    except Exception:
        return base_mask


def _remove_light_overlay_in_bbox(orig_rgb, mask, strength=7):
    """Estimate local background in the painted bbox and invert a light semi-transparent overlay."""
    if not HAS_CV2:
        return None
    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(mask, w, h, pad=max(6, strength * 2))
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox

        orig = np.array(orig_rgb.convert("RGB")).astype(np.float32)
        m = np.array(mask)
        _, m = cv2.threshold(m, 30, 255, cv2.THRESH_BINARY)
        if m.max() == 0:
            return None

        # Local background estimate from surrounding rows/cols only.
        bg_img = _painted_bbox_directional_fill(orig_rgb, mask, max(strength, 6))
        if bg_img is None:
            return None
        bg = np.array(bg_img.convert("RGB")).astype(np.float32)

        roi_orig = orig[y1:y2, x1:x2]
        roi_bg = bg[y1:y2, x1:x2]
        roi_mask = (m[y1:y2, x1:x2] > 0)
        if not roi_mask.any():
            return None

        # Estimate a light watermark color from the brightest masked pixels.
        diff = np.clip(roi_orig - roi_bg, 0, 255)
        score = diff.mean(axis=2)
        vals = score[roi_mask]
        if vals.size == 0:
            return None
        thresh = np.percentile(vals, 70)
        sample_mask = roi_mask & (score >= thresh)
        if sample_mask.sum() < 6:
            sample_mask = roi_mask
        wm_color = np.median(roi_orig[sample_mask], axis=0)
        wm_color = np.clip(wm_color, 210, 255)

        denom = np.clip(wm_color[None, None, :] - roi_bg, 8.0, 255.0)
        alpha = np.max((roi_orig - roi_bg) / denom, axis=2)
        alpha = np.clip(alpha, 0.0, 0.88)
        alpha *= roi_mask.astype(np.float32)
        alpha = cv2.GaussianBlur(alpha, (5, 5), 0)

        recovered = (roi_orig - alpha[:, :, None] * wm_color[None, None, :]) / np.clip(1.0 - alpha[:, :, None], 0.15, 1.0)
        recovered = np.clip(recovered, 0, 255)

        # Blend toward the estimated background when the overlay confidence is high.
        conf = np.clip((score / (score.max() + 1e-6)), 0, 1) * roi_mask.astype(np.float32)
        conf = cv2.GaussianBlur(conf, (5, 5), 0)[:, :, None]
        mixed = recovered * (1.0 - conf * 0.35) + roi_bg * (conf * 0.35)

        out = orig.copy()
        out[y1:y2, x1:x2] = np.where(roi_mask[:, :, None], mixed, out[y1:y2, x1:x2])
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    except Exception:
        return None


def _painted_bbox_directional_fill(orig_rgb, mask, strength=7):
    """Directional fill that only samples around the painted bbox, tuned for bottom-right text badges."""
    if not HAS_CV2:
        return None
    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(mask, w, h, pad=max(8, strength * 2))
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox

        img = np.array(orig_rgb.convert("RGB")).astype(np.float32)
        m = np.array(mask)
        _, m = cv2.threshold(m, 30, 255, cv2.THRESH_BINARY)
        out = np.array(_classical_inpaint(orig_rgb, mask, strength)).astype(np.float32)

        for yy in range(y1, y2):
            row_mask = m[yy, x1:x2] > 0
            if not row_mask.any():
                continue
            cols = np.where(row_mask)[0]
            seg_l = x1 + cols[0]
            seg_r = x1 + cols[-1]
            seg_w = max(1, seg_r - seg_l + 1)

            left_l = max(0, seg_l - seg_w * 2)
            left_r = seg_l
            left_strip = img[yy, left_l:left_r]
            if left_strip.size == 0:
                continue

            top_t = max(0, yy - max(6, strength * 2))
            top_strip = img[top_t:yy, seg_l:seg_r + 1]
            left_edge = left_strip[-1]
            fill_ref = left_strip.mean(axis=0)
            if top_strip.size > 0:
                fill_ref = 0.7 * fill_ref + 0.3 * top_strip.reshape(-1, 3).mean(axis=0)

            for xx in range(seg_l, seg_r + 1):
                t = (xx - seg_l) / max(1, seg_r - seg_l)
                out[yy, xx] = left_edge * (1.0 - t) + fill_ref * t

        roi_mask = m[y1:y2, x1:x2]
        blur = cv2.GaussianBlur(np.clip(out, 0, 255).astype(np.uint8), (5, 5), 0).astype(np.float32)
        alpha = (cv2.GaussianBlur(roi_mask, (5, 5), 0).astype(np.float32) / 255.0)[:, :, None]
        out[y1:y2, x1:x2] = out[y1:y2, x1:x2] * (1 - alpha) + blur[y1:y2, x1:x2] * alpha
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    except Exception:
        return None


def _detect_corner_watermark_mask(orig_rgb, base_mask, strength=7):
    """Expand mask for bottom-right corner watermarks like semi-transparent AI badges."""
    if not HAS_CV2:
        return base_mask

    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(base_mask, w, h, pad=max(18, strength * 4))
        if bbox is None:
            return base_mask
        x1, y1, x2, y2 = bbox

        # Only trigger on lower-right corner style masks.
        if x1 < int(w * 0.62) or y1 < int(h * 0.72):
            return base_mask

        rgb = np.array(orig_rgb.convert("RGB"))
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        base = np.array(base_mask)
        _, base_bin = cv2.threshold(base, 30, 255, cv2.THRESH_BINARY)

        roi = np.zeros((h, w), dtype=np.uint8)
        rx1 = max(0, x1 - max(24, strength * 6))
        ry1 = max(0, y1 - max(20, strength * 5))
        rx2 = min(w, x2 + max(10, strength * 2))
        ry2 = min(h, y2 + max(10, strength * 2))
        roi[ry1:ry2, rx1:rx2] = 255

        bright = cv2.inRange(hsv, (0, 0, 135), (180, 135, 255))
        grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
        edge = cv2.threshold(grad, 14, 255, cv2.THRESH_BINARY)[1]

        cand = cv2.bitwise_and(bright, roi)
        cand = cv2.bitwise_or(cand, cv2.bitwise_and(edge, roi))
        cand = cv2.morphologyEx(cand, cv2.MORPH_CLOSE, np.ones((3, 5), np.uint8), iterations=1)
        cand = cv2.dilate(cand, np.ones((3, 3), np.uint8), iterations=1)

        near = cv2.dilate(base_bin, np.ones((max(5, strength * 5), max(5, strength * 5)), np.uint8), iterations=1)
        num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(cand, 8)
        keep = base_bin.copy()
        for label in range(1, num_labels):
            x, y, cw, ch, area = stats[label]
            if area < 8 or area > int(w * h * 0.02):
                continue
            if x < int(w * 0.58) or y < int(h * 0.68):
                continue
            comp = (labels == label).astype(np.uint8) * 255
            if cv2.bitwise_and(comp, near).max() > 0:
                keep = cv2.bitwise_or(keep, comp)

        keep = cv2.morphologyEx(keep, cv2.MORPH_CLOSE, np.ones((3, 7), np.uint8), iterations=1)
        keep = cv2.dilate(keep, np.ones((3, 3), np.uint8), iterations=1)
        return Image.fromarray(keep)
    except Exception:
        return base_mask


def _is_bottom_right_corner_mask(mask, size):
    bbox = _get_mask_bbox(mask, size[0], size[1], pad=0)
    if bbox is None:
        return False
    x1, y1, x2, y2 = bbox
    w, h = size
    area = max(1, (x2 - x1) * (y2 - y1))
    return x1 >= int(w * 0.62) and y1 >= int(h * 0.72) and area <= int(w * h * 0.08)


def _corner_banner_fill(orig_rgb, mask, strength=7):
    """Fill bottom-right badge regions using left/top neighboring banner texture."""
    if not HAS_CV2:
        return None
    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(mask, w, h, pad=max(10, strength * 2))
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        img = np.array(orig_rgb.convert("RGB")).astype(np.float32)
        m = np.array(mask)
        _, m = cv2.threshold(m, 30, 255, cv2.THRESH_BINARY)

        out = img.copy()
        roi_mask = m[y1:y2, x1:x2]
        if roi_mask.max() == 0:
            return None

        # Base fill from classical inpaint as initialization.
        init = np.array(_classical_inpaint(orig_rgb, mask, strength)).astype(np.float32)
        out[y1:y2, x1:x2] = init[y1:y2, x1:x2]

        left_band_w = max(12, min(x1, (x2 - x1) * 2))
        top_band_h = max(8, min(y1, (y2 - y1)))

        for yy in range(y1, y2):
            row = m[yy, x1:x2] > 0
            if not row.any():
                continue
            cols = np.where(row)[0]
            seg_l = x1 + cols[0]
            seg_r = x1 + cols[-1]

            left_src_l = max(0, seg_l - left_band_w)
            left_src_r = max(left_src_l + 1, seg_l)
            left_strip = out[yy, left_src_l:left_src_r]
            if left_strip.size == 0:
                continue

            left_mean = left_strip.mean(axis=0)
            left_edge = left_strip[-1]
            right_ref = left_mean
            if y1 >= top_band_h:
                top_slice = out[max(0, yy - top_band_h):yy, seg_l:seg_r + 1]
                if top_slice.size > 0:
                    right_ref = 0.6 * left_mean + 0.4 * top_slice.reshape(-1, 3).mean(axis=0)

            span = max(1, seg_r - seg_l)
            for xx in range(seg_l, seg_r + 1):
                t = (xx - seg_l) / span
                out[yy, xx] = left_edge * (1.0 - 0.75 * t) + right_ref * (0.75 * t)

        # Smooth only inside the repaired corner mask.
        blur = cv2.GaussianBlur(np.clip(out, 0, 255).astype(np.uint8), (5, 5), 0).astype(np.float32)
        alpha = (cv2.GaussianBlur(roi_mask, (5, 5), 0).astype(np.float32) / 255.0)[:, :, None]
        out[y1:y2, x1:x2] = out[y1:y2, x1:x2] * (1 - alpha) + blur[y1:y2, x1:x2] * alpha
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    except Exception:
        return None


def _doubao_banner_patch_fill(orig_rgb, mask, strength=7):
    """Fill the bottom-right watermark by matching a nearby clean banner patch on the left."""
    if not HAS_CV2:
        return None
    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(mask, w, h, pad=max(4, strength))
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        if y1 < int(h * 0.78):
            return None

        img = np.array(orig_rgb.convert("RGB")).astype(np.uint8)
        mask_arr = np.array(mask)
        _, mask_bin = cv2.threshold(mask_arr, 30, 255, cv2.THRESH_BINARY)
        bw = max(1, x2 - x1)
        bh = max(1, y2 - y1)
        if x1 < max(20, bw // 2):
            return None

        target = img[y1:y2, x1:x2].astype(np.float32)
        left_ctx = img[y1:y2, max(0, x1 - min(12, x1)):x1].astype(np.float32)
        top_ctx = img[max(0, y1 - min(8, y1)):y1, x1:x2].astype(np.float32)

        best_score = None
        best_patch = None
        x_min = max(0, x1 - bw * 4)
        x_max = max(0, x1 - max(8, strength))
        step = max(2, bw // 12)

        for sx in range(x_min, x_max + 1, step):
            ex = sx + bw
            if ex > x1:
                break
            patch = img[y1:y2, sx:ex]
            if patch.shape[0] != bh or patch.shape[1] != bw:
                continue
            patch_f = patch.astype(np.float32)

            score = 0.0
            if left_ctx.size > 0:
                patch_left = patch_f[:, :left_ctx.shape[1]]
                score += float(((patch_left - left_ctx) ** 2).mean())
            if top_ctx.size > 0:
                patch_top = patch_f[:top_ctx.shape[0], :]
                score += float(((patch_top - top_ctx) ** 2).mean()) * 0.6

            # Prefer darker banner tone continuity over bright copied artifacts.
            score += float(np.abs(patch_f.mean() - target.mean())) * 0.15

            if best_score is None or score < best_score:
                best_score = score
                best_patch = patch_f

        if best_patch is None:
            return None

        # Adjust patch tone row-by-row to match the banner gradient near the target.
        patch = best_patch.copy()
        for row in range(bh):
            left_ref = img[y1 + row, max(0, x1 - min(16, x1)):x1].astype(np.float32)
            if left_ref.size == 0:
                continue
            patch_ref = patch[row, :min(16, bw)]
            delta = left_ref.mean(axis=0) - patch_ref.mean(axis=0)
            patch[row] = np.clip(patch[row] + delta * 0.85, 0, 255)

        alpha = cv2.GaussianBlur(mask_bin[y1:y2, x1:x2], (5, 5), 0).astype(np.float32) / 255.0
        alpha = alpha[:, :, None]
        out = img.copy().astype(np.float32)
        out[y1:y2, x1:x2] = patch * alpha + target * (1 - alpha)
        return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    except Exception:
        return None


def _doubao_local_texture_fill(orig_rgb, mask, strength=7):
    """Use only the nearby neighborhood around the painted bbox for texture completion."""
    if not HAS_CV2:
        return None
    try:
        w, h = orig_rgb.size
        bbox = _get_mask_bbox(mask, w, h, pad=max(18, strength * 4))
        if bbox is None:
            return None
        x1, y1, x2, y2 = bbox
        roi = orig_rgb.crop((x1, y1, x2, y2))
        roi_mask = mask.crop((x1, y1, x2, y2))
        repaired = _patch_match_inpaint(roi, roi_mask, max(strength, 6))
        if repaired is None:
            return None
        out = orig_rgb.copy()
        out.paste(repaired, (x1, y1))
        return _post_blend_inpaint(orig_rgb, out, mask, feather=3)
    except Exception:
        return None


def remove_doubao_watermark(orig_rgb, mask, strength=7, progress_cb=None):
    """Dedicated remover for the bottom-right semi-transparent `豆包AI生成` style watermark."""
    refined_mask = _refine_text_watermark_mask(orig_rgb, mask, strength)
    refined_mask = _detect_painted_doubao_mask(orig_rgb, refined_mask, strength)

    if progress_cb:
        progress_cb("豆包角标检测中…")

    if _is_bottom_right_corner_mask(refined_mask, orig_rgb.size):
        if progress_cb:
            progress_cb("优先使用局部纹理贴补修复角标…")
        result = _doubao_local_texture_fill(orig_rgb, refined_mask, max(strength, 7))
        if result is not None:
            residual_mask = _detect_painted_doubao_mask(result, refined_mask, max(strength - 2, 3))
            residual = _classical_inpaint(result, residual_mask, max(strength - 1, 4))
            return _post_blend_inpaint(orig_rgb, residual, residual_mask, feather=3)

        if progress_cb:
            progress_cb("局部纹理贴补不足，改用底栏贴片修复…")
        result = _doubao_banner_patch_fill(orig_rgb, refined_mask, max(strength, 7))
        if result is not None:
            residual_mask = _detect_painted_doubao_mask(result, refined_mask, max(strength - 2, 3))
            residual = _classical_inpaint(result, residual_mask, max(strength - 1, 4))
            return _post_blend_inpaint(orig_rgb, residual, residual_mask, feather=3)

        if progress_cb:
            progress_cb("贴片修复不足，改用透明层反解…")
        result = _remove_light_overlay_in_bbox(orig_rgb, refined_mask, max(strength, 7))
        if result is not None:
            residual_mask = _detect_painted_doubao_mask(result, refined_mask, max(strength - 1, 4))
            residual = _classical_inpaint(result, residual_mask, max(strength - 1, 5))
            residual = _remove_light_overlay_in_bbox(residual, residual_mask, max(strength - 1, 5)) or residual
            return _post_blend_inpaint(orig_rgb, residual, residual_mask, feather=4)

        if progress_cb:
            progress_cb("透明层反解不足，回退到局部定向补底…")
        result = _painted_bbox_directional_fill(orig_rgb, refined_mask, max(strength, 7))
        if result is not None:
            return _post_blend_inpaint(orig_rgb, result, refined_mask, feather=4)

    if progress_cb:
        progress_cb("豆包角标专项不足，回退到局部去水印…")
    return local_inpaint(orig_rgb, refined_mask, strength=max(strength, 7), progress_cb=progress_cb)


def local_inpaint(orig_rgb, mask, strength=7, progress_cb=None):
    """Local inpaint entry: stay inside the painted region and specialize for `豆包AI生成` style corner text."""
    refined_mask = _refine_text_watermark_mask(orig_rgb, mask, strength)
    refined_mask = _detect_painted_doubao_mask(orig_rgb, refined_mask, strength)

    if _is_bottom_right_corner_mask(refined_mask, orig_rgb.size):
        if progress_cb:
            progress_cb("仅按涂抹区域执行豆包角标专项修复…")
        corner_result = _remove_light_overlay_in_bbox(orig_rgb, refined_mask, max(strength, 6))
        if corner_result is not None:
            return _post_blend_inpaint(orig_rgb, corner_result, refined_mask)
        if progress_cb:
            progress_cb("透明层反解不足，回退到局部定向补底…")
        corner_result = _painted_bbox_directional_fill(orig_rgb, refined_mask, max(strength, 6))
        if corner_result is not None:
            return _post_blend_inpaint(orig_rgb, corner_result, refined_mask)

    flat_result, is_flat = _detect_flat_bg_and_fill(orig_rgb, refined_mask, strength)
    if is_flat and flat_result is not None:
        if progress_cb:
            progress_cb("检测到纯色背景，直接智能补色…")
        flat_result = _recover_white_overlay(orig_rgb, flat_result, refined_mask)
        return _post_blend_inpaint(orig_rgb, flat_result, refined_mask)

    result = _torch_generative_inpaint(orig_rgb, refined_mask, strength, progress_cb)
    if result is not None:
        result = _recover_white_overlay(orig_rgb, result, refined_mask)
        result = _post_blend_inpaint(orig_rgb, result, refined_mask)
        patch = _patch_match_inpaint(result, refined_mask, max(strength, 6))
        patch = _recover_white_overlay(orig_rgb, patch, refined_mask)
        return _post_blend_inpaint(orig_rgb, _color_align(orig_rgb, patch, refined_mask), refined_mask)

    if progress_cb:
        progress_cb("局部生成式修复不足，切换到局部纹理拼接…")
    result = _patch_match_inpaint(orig_rgb, refined_mask, max(strength, 6))
    if result is not None:
        result = _recover_white_overlay(orig_rgb, result, refined_mask)
        return _post_blend_inpaint(orig_rgb, _color_align(orig_rgb, result, refined_mask), refined_mask)

    result = _torch_frequency_inpaint(orig_rgb, refined_mask, strength, progress_cb)
    if result is not None:
        result = _recover_white_overlay(orig_rgb, result, refined_mask)
        return _post_blend_inpaint(orig_rgb, result, refined_mask)

    if progress_cb:
        progress_cb("使用 OpenCV 经典修复兜底…")
    result = _classical_inpaint(orig_rgb, refined_mask, strength)
    result = _recover_white_overlay(orig_rgb, result, refined_mask)
    return _post_blend_inpaint(orig_rgb, result, refined_mask)

    if progress_cb:
        progress_cb("使用 OpenCV 经典修复兜底…")
    result = _classical_inpaint(orig_rgb, refined_mask, strength)
    result = _recover_white_overlay(orig_rgb, result, overlay_mask)
    return _post_blend_inpaint(orig_rgb, result, refined_mask)


def get_local_backend_info():
    """Return the currently available local backend description for UI display."""
    if HAS_TORCH and HAS_CUDA:
        return "CUDA生成式填充 + CUDA ✅"
    if HAS_TORCH and HAS_NVIDIA_GPU:
        return "PyTorch CPU版（已检测到 NVIDIA 显卡，当前未安装 CUDA 版 Torch）"
    if HAS_TORCH:
        return "PyTorch CPU版"
    if HAS_CV2:
        return "OpenCV TELEA+NS"
    return "PIL基础算法"


def _detect_flat_bg_and_fill(orig_rgb, mask, strength=7):
    """
    纯色/渐变背景检测与填充：
    当水印区域周边背景颜色方差很低（纯色块）时，
    直接用插值填充，效果远好于 TELEA/NS。
    返回 (result, is_flat)，is_flat=True 表示使用了此方法。
    """
    if not HAS_CV2:
        return None, False

    img_arr  = np.array(orig_rgb).astype(np.float32)
    msk_arr  = np.array(mask)
    _, msk_bin = cv2.threshold(msk_arr, 30, 255, cv2.THRESH_BINARY)

    # 采样蒙版周边一圈（宽度约 strength*4 像素）的颜色
    sample_k = np.ones((max(5, strength * 4), max(5, strength * 4)), np.uint8)
    dilated  = cv2.dilate(msk_bin, sample_k, iterations=1)
    border   = (dilated > 0) & (msk_bin == 0)

    if border.sum() < 20:
        return None, False

    border_pixels = img_arr[border]  # shape (N, 3)
    std_per_channel = border_pixels.std(axis=0)   # (3,)
    mean_color      = border_pixels.mean(axis=0)  # (3,)

    # 如果三通道标准差均小于阈值，认为是纯色/低纹理背景
    flat_threshold = 28.0
    is_flat = bool(std_per_channel.max() < flat_threshold)

    if not is_flat:
        return None, False

    result_arr = img_arr.copy()
    zone = msk_bin > 0

    # 对纯色区域：用双线性距离权重从四周颜色插值填充
    # 1. 先整体填充均值色
    result_arr[zone] = mean_color

    # 2. 对每行/列做水平方向插值（左右边缘颜色过渡）
    h, w = img_arr.shape[:2]
    for row in range(h):
        row_mask = msk_bin[row]
        if row_mask.max() == 0:
            continue
        cols = np.where(row_mask > 0)[0]
        if len(cols) == 0:
            continue
        c_left  = max(0, cols[0] - 1)
        c_right = min(w - 1, cols[-1] + 1)
        left_color  = img_arr[row, c_left]  if msk_bin[row, c_left]  == 0 else mean_color
        right_color = img_arr[row, c_right] if msk_bin[row, c_right] == 0 else mean_color
        for c in cols:
            t = (c - c_left) / max(1, c_right - c_left)
            result_arr[row, c] = left_color * (1 - t) + right_color * t

    # 3. 与垂直方向插值结果做 50/50 混合
    result_v = img_arr.copy()
    result_v[zone] = mean_color
    for col in range(w):
        col_mask = msk_bin[:, col]
        if col_mask.max() == 0:
            continue
        rows = np.where(col_mask > 0)[0]
        if len(rows) == 0:
            continue
        r_top    = max(0, rows[0] - 1)
        r_bottom = min(h - 1, rows[-1] + 1)
        top_color    = img_arr[r_top,    col] if msk_bin[r_top,    col] == 0 else mean_color
        bottom_color = img_arr[r_bottom, col] if msk_bin[r_bottom, col] == 0 else mean_color
        for r in rows:
            t = (r - r_top) / max(1, r_bottom - r_top)
            result_v[r, col] = top_color * (1 - t) + bottom_color * t

    # 融合水平 + 垂直
    blended = np.where(
        zone[:, :, np.newaxis],
        (result_arr * 0.5 + result_v * 0.5),
        img_arr
    ).astype(np.float32)

    # 轻微高斯平滑消除接缝
    blended_u8 = np.clip(blended, 0, 255).astype(np.uint8)
    smooth     = cv2.GaussianBlur(blended_u8, (5, 5), 0)
    feather_k  = np.ones((5, 5), np.uint8)
    feather_m  = cv2.dilate(msk_bin, feather_k, iterations=2)
    alpha_f    = (feather_m[:, :, np.newaxis] / 255.0 * 0.4).astype(np.float32)
    final      = (blended_u8.astype(np.float32) * (1 - alpha_f) +
                  smooth.astype(np.float32) * alpha_f).astype(np.uint8)

    return Image.fromarray(final), True


def _classical_inpaint(orig_rgb, mask, strength=7):
    """OpenCV TELEA + NS 双算法融合修复，内置纯色背景快速路径"""
    # 先尝试纯色填充（比 TELEA 效果好得多，速度也更快）
    flat_result, is_flat = _detect_flat_bg_and_fill(orig_rgb, mask, strength)
    if is_flat and flat_result is not None:
        return flat_result

    if not HAS_CV2:
        blurred = orig_rgb.filter(ImageFilter.GaussianBlur(radius=max(2, strength * 3)))
        out = orig_rgb.copy()
        out.paste(blurred, mask=mask)
        return out

    img_arr = np.array(orig_rgb)
    mask_arr = np.array(mask)
    _, mask_bin = cv2.threshold(mask_arr, 30, 255, cv2.THRESH_BINARY)

    # 膨胀蒙版，确保水印边缘完整覆盖
    kernel = np.ones((5, 5), np.uint8)
    mask_dilated = cv2.dilate(mask_bin, kernel, iterations=2)

    radius = max(5, strength * 2)

    # TELEA 算法：边缘传播，适合规则背景
    result_telea = cv2.inpaint(img_arr, mask_dilated, radius, cv2.INPAINT_TELEA)
    # NS 算法：纳维-斯托克斯，适合纹理背景
    result_ns = cv2.inpaint(img_arr, mask_dilated, radius, cv2.INPAINT_NS)

    # 融合：用蒙版距离变换做渐变混合
    dist = cv2.distanceTransform(mask_dilated, cv2.DIST_L2, 5)
    if dist.max() > 0:
        dist_norm = np.clip(dist / dist.max(), 0, 1)
    else:
        dist_norm = np.zeros_like(dist)
    alpha = dist_norm[:, :, np.newaxis].astype(np.float32)
    blended = (result_telea.astype(np.float32) * (1 - alpha * 0.4) +
               result_ns.astype(np.float32) * alpha * 0.4).astype(np.uint8)

    # 在修复区域边缘做轻微羽化，减少接缝感
    edge_kernel = np.ones((3, 3), np.uint8)
    edge_mask = cv2.dilate(mask_dilated, edge_kernel, iterations=3) - mask_dilated
    if edge_mask.max() > 0:
        edge_blur = cv2.GaussianBlur(blended, (5, 5), 0)
        edge_alpha = (edge_mask[:, :, np.newaxis] / 255.0 * 0.5).astype(np.float32)
        blended = (blended.astype(np.float32) * (1 - edge_alpha) +
                   edge_blur.astype(np.float32) * edge_alpha).astype(np.uint8)

    return Image.fromarray(blended)


def _patch_match_inpaint(orig_rgb, mask, strength=7):
    """
    基于 PatchMatch 思路的纹理合成修复：
    从蒙版周围采样相似 patch，逐步填充遮挡区域。
    不依赖 OpenCV，纯 PIL + numpy 实现。
    """
    if not HAS_CV2:
        return _classical_inpaint(orig_rgb, mask, strength)

    img = np.array(orig_rgb).astype(np.float32)
    msk = np.array(mask)
    _, msk_bin = cv2.threshold(msk, 30, 255, cv2.THRESH_BINARY)

    patch_size = max(7, strength * 2 + 1)
    if patch_size % 2 == 0:
        patch_size += 1
    half = patch_size // 2

    h, w = img.shape[:2]
    result = img.copy()
    mask_bool = msk_bin > 0

    # 获取需要填充的像素坐标（按距离边缘从近到远排序）
    dist = cv2.distanceTransform((msk_bin > 0).astype(np.uint8) * 255,
                                  cv2.DIST_L2, 5)
    fill_coords = np.argwhere(mask_bool)
    if len(fill_coords) == 0:
        return orig_rgb

    # 按距离从小到大填充（先填靠近边缘的像素）
    distances = dist[fill_coords[:, 0], fill_coords[:, 1]]
    order = np.argsort(distances)
    fill_coords = fill_coords[order]

    # 采样候选区域：蒙版外的有效像素
    valid_mask = ~mask_bool
    # 用经典修复先做一遍作为初始值
    init = np.array(_classical_inpaint(orig_rgb, mask, strength)).astype(np.float32)
    result = init.copy()

    # 对每个填充像素，找周边最相似的 patch 来填充
    sample_step = max(1, len(fill_coords) // 2000)  # 限制迭代数量
    for idx in range(0, len(fill_coords), sample_step):
        py, px = fill_coords[idx]
        # 当前 patch 的边界像素（用于匹配）
        y1, y2 = max(0, py - half), min(h, py + half + 1)
        x1, x2 = max(0, px - half), min(w, px + half + 1)

        # 在已知区域随机采样若干候选 patch
        best_score = float('inf')
        best_patch = None
        candidates = 40 if len(fill_coords) < 8000 else 24

        for _ in range(candidates):
            ry = np.random.randint(half, h - half)
            rx = np.random.randint(half, w - half)
            # 候选 patch 必须完全在有效区域
            cand_region = valid_mask[ry-half:ry+half+1, rx-half:rx+half+1]
            if cand_region.shape != (patch_size, patch_size):
                continue
            if not cand_region.all():
                continue
            cand_patch = result[ry-half:ry+half+1, rx-half:rx+half+1]
            cur_patch = result[y1:y2, x1:x2]
            if cand_patch.shape != cur_patch.shape:
                continue
            # 只比较已知像素的误差
            known = ~mask_bool[y1:y2, x1:x2]
            if known.sum() == 0:
                continue
            diff = ((cand_patch[known] - cur_patch[known]) ** 2).mean()
            if diff < best_score:
                best_score = diff
                best_patch = cand_patch

        if best_patch is not None:
            # 只更新蒙版内的中心像素
            result[py, px] = best_patch[py - y1, px - x1]

    # 最终在修复区域做轻微平滑，消除块状感
    result_img = result.astype(np.uint8)
    result_pil = Image.fromarray(result_img)
    smooth = np.array(result_pil.filter(ImageFilter.GaussianBlur(radius=1)))
    # 只在蒙版区域应用平滑
    alpha_msk = (msk_bin[:, :, np.newaxis] / 255.0 * 0.4).astype(np.float32)
    final = (result_img.astype(np.float32) * (1 - alpha_msk) +
             smooth.astype(np.float32) * alpha_msk).astype(np.uint8)

    return Image.fromarray(final)


def _build_context_crop(orig_rgb, mask, x1, y1, x2, y2):
    """
    构建发给 Claude 的上下文图：
    - 裁剪水印区域（含周边）
    - 在裁剪图上用黑色实心矩形遮住水印，模拟"缺失"状态
    - 让 Claude 看到上下文并推断应该填什么
    """
    crop = orig_rgb.crop((x1, y1, x2, y2))
    cw, ch = crop.size

    # 在裁剪图上将蒙版区域涂黑（表示"需要填充"）
    masked_crop = crop.copy()
    draw = ImageDraw.Draw(masked_crop)
    # 把蒙版对应到裁剪坐标系
    for py in range(y1, y2):
        for px in range(x1, x2):
            try:
                if mask.getpixel((px, py)) > 30:
                    draw.point((px - x1, py - y1), fill=(0, 0, 0))
            except Exception:
                pass

    return crop, masked_crop


def ai_inpaint_via_claude(original, mask, strength=7, progress_cb=None):
    """
    多策略融合去水印：
    1. 用 Claude API 分析水印区域周边背景，生成高质量修复参考图
    2. 用 OpenCV 双算法融合（TELEA + NS）做精确像素修复
    3. 对修复结果做色调 / 亮度对齐，消除色差
    4. 边缘羽化融合，无缝拼接
    """
    orig_rgb = original.convert("RGB")
    w, h = orig_rgb.size

    bbox = _get_mask_bbox(mask, w, h, pad=80)
    if bbox is None:
        return orig_rgb

    x1, y1, x2, y2 = bbox

    # ── Step 1: 经典双算法修复（始终执行，作为基础层）─────────────────
    if progress_cb:
        progress_cb("Step 1/3：OpenCV 双算法修复中…")

    base_result = _classical_inpaint(orig_rgb, mask, strength)

    # ── Step 2: Claude API 分析 + 生成参考补丁 ─────────────────────────
    if not HAS_REQUESTS:
        return base_result

    api_key = _get_api_key()
    if not api_key:
        if progress_cb:
            progress_cb("⚠ 未配置 API Key，已使用本地算法修复。请在「AI设置」中填写 Key。")
        return base_result

    try:
        if progress_cb:
            progress_cb("Step 2/3：发送至 Claude AI 分析背景纹理…")

        # 裁剪上下文区域（缩放到合理大小节省 token）
        crop_orig = orig_rgb.crop((x1, y1, x2, y2))
        crop_w, crop_h = crop_orig.size

        # 蒙版裁剪
        crop_mask = mask.crop((x1, y1, x2, y2))

        # 在裁剪图上把水印区域涂为显眼的洋红色，让 Claude 精确定位
        annotated = crop_orig.copy().convert("RGBA")
        ann_draw = ImageDraw.Draw(annotated)
        mask_arr_crop = list(crop_mask.getdata())
        for idx, v in enumerate(mask_arr_crop):
            if v > 30:
                px = idx % crop_w
                py = idx // crop_w
                ann_draw.point((px, py), fill=(255, 0, 255, 200))
        annotated_rgb = annotated.convert("RGB")

        # 同时发送：① 完整原图（给 Claude 全局背景理解）
        #           ② 裁剪的局部上下文（高精度分析）
        #           ③ 标注了水印位置的裁剪图
        full_b64 = _pil_to_base64(orig_rgb.resize(
            (min(w, 1024), min(h, 1024)), Image.Resampling.LANCZOS))
        crop_b64 = _pil_to_base64(crop_orig)
        annot_b64 = _pil_to_base64(annotated_rgb)

        # 同时发：base_result 的对应裁剪，让 Claude 评价修复质量
        base_crop = base_result.crop((x1, y1, x2, y2))
        base_b64 = _pil_to_base64(base_crop)

        prompt = """You are a professional image inpainting AI. I need to remove a watermark from an image.

Image 1: Full original image (for global context understanding)
Image 2: Cropped region around the watermark area  
Image 3: Same crop with the watermark area highlighted in MAGENTA/PINK pixels
Image 4: A preliminary inpainting result (using classical algorithm) of the watermark area

Your task: Analyze the background texture, color, pattern, and lighting in the NON-magenta areas of Image 2/3. Then evaluate Image 4 and describe specifically what corrections are needed to make the inpainted area seamlessly blend with the surrounding background.

Respond in JSON format only, no markdown:
{
  "background_color_rgb": [R, G, B],
  "background_description": "brief description of texture/pattern",
  "inpaint_quality": "good|fair|poor",
  "corrections_needed": "specific corrections: e.g. too bright, wrong texture, color cast etc",
  "blend_direction": "which edge colors to sample from: left|right|top|bottom|all"
}"""

        payload = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 500,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": full_b64}},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": crop_b64}},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": annot_b64}},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base_b64}},
                    {"type": "text", "text": prompt}
                ]
            }]
        }

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": _get_api_key(),
                "anthropic-version": "2023-06-01",
            },
            json=payload,
            timeout=45
        )

        analysis = {}
        if resp.status_code == 200:
            raw = ""
            for block in resp.json().get("content", []):
                if block.get("type") == "text":
                    raw += block["text"]
            # 清理 JSON
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            try:
                analysis = json.loads(raw.strip())
            except Exception:
                analysis = {}

        if progress_cb:
            quality = analysis.get("inpaint_quality", "unknown")
            desc = analysis.get("background_description", "")
            progress_cb(f"Step 2/3：AI分析完成（质量={quality}）：{desc[:40]}")

        # ── Step 3: 根据 AI 分析做色调矫正 + 精细融合 ─────────────────
        if progress_cb:
            progress_cb("Step 3/3：色调对齐与边缘融合…")

        if not HAS_CV2:
            return base_result

        result_arr = np.array(base_result).astype(np.float32)
        orig_arr = np.array(orig_rgb).astype(np.float32)
        mask_arr = np.array(mask)
        _, mask_bin = cv2.threshold(mask_arr, 30, 255, cv2.THRESH_BINARY)

        # 采样修复区域周围一圈的颜色，用于色调对齐
        kernel_sample = np.ones((25, 25), np.uint8)
        dilated_sample = cv2.dilate(mask_bin, kernel_sample, iterations=1)
        border_zone = (dilated_sample > 0) & (mask_bin == 0)

        if border_zone.sum() > 10:
            # 周边区域的颜色统计（原图）
            border_orig = orig_arr[border_zone]
            border_result = result_arr[border_zone]

            orig_mean = border_orig.mean(axis=0)
            result_mean = border_result.mean(axis=0)
            orig_std = border_orig.std(axis=0) + 1e-6
            result_std = border_result.std(axis=0) + 1e-6

            # 对修复区域做颜色统计匹配（均值+方差对齐）
            mask_zone = mask_bin > 0
            if mask_zone.sum() > 0:
                repaired_pixels = result_arr[mask_zone]
                # 均值偏移
                color_shift = orig_mean - result_mean
                # 方差缩放（轻度，避免过度矫正）
                scale = np.clip(orig_std / result_std, 0.7, 1.4)

                corrected = (repaired_pixels - result_mean) * scale * 0.5 + result_mean + color_shift * 0.6
                corrected = np.clip(corrected, 0, 255)
                result_arr[mask_zone] = corrected

        # AI 建议的背景色额外参考
        if "background_color_rgb" in analysis:
            try:
                ai_color = np.array(analysis["background_color_rgb"], dtype=np.float32)
                if ai_color.shape == (3,):
                    mask_zone = mask_bin > 0
                    if mask_zone.sum() > 0:
                        # 轻度向 AI 建议色偏移（权重 15%，避免过度）
                        result_arr[mask_zone] = (
                            result_arr[mask_zone] * 0.85 + ai_color * 0.15
                        )
            except Exception:
                pass

        result_arr = np.clip(result_arr, 0, 255).astype(np.uint8)

        # 最终边缘羽化：用 Gaussian 权重在蒙版边缘做渐变混合
        feather_kernel = np.ones((9, 9), np.uint8)
        feather_mask = cv2.dilate(mask_bin, feather_kernel, iterations=3)
        feather_dist = cv2.distanceTransform(feather_mask, cv2.DIST_L2, 5)
        inner_dist = cv2.distanceTransform(mask_bin, cv2.DIST_L2, 5)

        # 构建羽化权重：蒙版内部=1，边缘渐变到0
        feather_w = np.zeros_like(feather_dist)
        border_w = feather_mask > 0
        feather_w[border_w] = np.clip(
            inner_dist[border_w] / (feather_dist[border_w] + 1e-6), 0, 1
        )
        feather_w = feather_w[:, :, np.newaxis].astype(np.float32)

        final = (result_arr.astype(np.float32) * feather_w +
                 orig_arr * (1 - feather_w)).astype(np.uint8)

        # 只对蒙版区域应用 final，其余保持原图
        output = orig_arr.copy().astype(np.uint8)
        output[feather_mask > 0] = final[feather_mask > 0]

        if progress_cb:
            progress_cb("✅ AI去水印完成！")

        return Image.fromarray(output)

    except Exception as e:
        if progress_cb:
            progress_cb(f"AI分析异常，使用本地算法：{str(e)[:40]}")
        return base_result


# ─────────────────────────────────────────────
#  Main module class
# ─────────────────────────────────────────────

class AIWatermarkRemoveModule:
    """
    AI去水印模块：
    - 手动涂抹水印区域（支持笔刷大小、硬度）
    - 点击"AI一键去水印"：先用 Claude API 分析区域，再用 OpenCV TELEA 算法还原背景
    - 支持批量处理（自动检测相似水印位置后去除）
    - 撤销 / 重做 / 清空蒙版
    - 保存前对比预览
    """

    def __init__(self, parent_frame, create_progress_window, update_progress, finish_processing):
        self.parent_frame = parent_frame
        self.create_progress_window = create_progress_window
        self.update_progress = update_progress
        self.finish_processing = finish_processing

        self.input_path = tk.StringVar(value=os.getcwd())
        self.output_dir = tk.StringVar()
        self.include_subdirs = tk.BooleanVar(value=False)
        self.brush_size = tk.IntVar(value=22)
        self.brush_hardness = tk.IntVar(value=60)
        self.strength = tk.IntVar(value=7)
        self.output_format = tk.StringVar(value="png")
        self.tool_mode = tk.StringVar(value="paint")   # paint | erase
        self.show_mask = tk.BooleanVar(value=True)
        self.compare_mode = tk.BooleanVar(value=False)
        self.batch_apply_mask = tk.BooleanVar(value=False)
        self.repair_mode = tk.StringVar(value="local")   # ai | local | fast

        self.original_image = None  # type: Image.Image
        self.repaired_image = None  # type: Image.Image
        self.mask_image = None  # type: Image.Image  # 'L' mode
        self.tk_preview = None
        self.tk_preview_left = None
        self.tk_preview_right = None
        self.scale_ratio = 1.0
        self.last_x = None
        self.last_y = None
        self.last_cx = None
        self.last_cy = None
        self.undo_stack = []
        self.redo_stack = []
        self.history_records = []
        self._ai_running = False
        self._saved_mask = None   # type: Image.Image  # for batch

        self.input_path.trace_add("write", self.on_input_changed)
        self.create_ui()
        self.bind_shortcuts()
        self.on_input_changed()

    # ── UI ───────────────────────────────────────────────────────────

    def create_ui(self):
        body = tb.Frame(self.parent_frame)
        body.pack(fill=BOTH, expand=YES)

        # 左侧加滚动条，防止内容过多被截断
        left_outer = tb.Frame(body)
        left_outer.pack(side=LEFT, fill=Y, padx=(0, 12))
        left_canvas = tk.Canvas(left_outer, highlightthickness=0, width=424)
        left_scroll = tb.Scrollbar(left_outer, orient="vertical", command=left_canvas.yview)
        left_canvas.configure(yscrollcommand=left_scroll.set)
        left_scroll.pack(side=RIGHT, fill=Y)
        left_canvas.pack(side=LEFT, fill=Y, expand=NO)
        left = tb.Frame(left_canvas)
        self._left_win = left_canvas.create_window((0, 0), window=left, anchor="nw")
        def _on_left_configure(e):
            left_canvas.configure(scrollregion=left_canvas.bbox("all"))
        left.bind("<Configure>", _on_left_configure)
        def _on_mousewheel(e):
            left_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        left_canvas.bind("<MouseWheel>", _on_mousewheel)
        left.bind("<MouseWheel>", _on_mousewheel)

        right = tb.Frame(body)
        right.pack(side=LEFT, fill=BOTH, expand=YES)

        # I/O
        io_box, io_inner = make_card(left, "输入输出", "选择图片和结果保存位置")
        self.input_entry = create_input_row(io_inner, "输入路径:", self.input_path)
        create_output_row(io_inner, "输出目录:", self.output_dir)
        tb.Checkbutton(io_inner, text="批量处理子目录", variable=self.include_subdirs,
                       bootstyle="round-toggle").pack(anchor=W, pady=(6, 0))

        # API Key 配置
        api_box, api_inner = make_card(left, "🔑 API Key 配置", "填写后即可使用 AI 精细模式")
        key_row = tb.Frame(api_inner); key_row.pack(fill=X, pady=4)
        tb.Label(key_row, text="API Key:", width=10, anchor=W).pack(side=LEFT)
        self._api_key_var = tk.StringVar(value=_load_api_key())
        self._api_key_entry = tb.Entry(key_row, textvariable=self._api_key_var, show="*", width=24)
        self._api_key_entry.pack(side=LEFT, fill=X, expand=YES, padx=(0, 6))
        tb.Button(key_row, text="👁", width=3, bootstyle="secondary-outline",
                  command=self._toggle_key_visibility).pack(side=LEFT)

        hint_row = tb.Frame(api_inner); hint_row.pack(fill=X, pady=(2, 4))
        tb.Label(hint_row,
                 text="前往 console.anthropic.com 创建 Key（sk-ant-...）",
                 bootstyle="secondary", font=("微软雅黑", 8)).pack(anchor=W)

        btn_row = tb.Frame(api_inner); btn_row.pack(fill=X)
        tb.Button(btn_row, text="保存 Key", bootstyle="primary-outline", width=12,
                  command=self._save_api_key_ui).pack(side=LEFT)
        tb.Button(btn_row, text="清除 Key", bootstyle="danger-outline", width=12,
                  command=self._clear_api_key_ui).pack(side=LEFT, padx=6)
        self._key_status_lbl = tb.Label(btn_row, text="", bootstyle="success",
                                        font=("微软雅黑", 9))
        self._key_status_lbl.pack(side=LEFT)
        # 初始显示Key状态
        self._refresh_key_status()

        # Brush settings
        cfg, cfg_inner = make_card(left, "涂抹设置", "调整笔刷大小、硬度与工具模式")

        r0 = tb.Frame(cfg_inner); r0.pack(fill=X, pady=4)
        tb.Label(r0, text="工具:", width=10, anchor=W).pack(side=LEFT)
        tb.Radiobutton(r0, text="涂抹", variable=self.tool_mode, value="paint",
                       bootstyle="toolbutton-outline").pack(side=LEFT, padx=3)
        tb.Radiobutton(r0, text="橡皮擦", variable=self.tool_mode, value="erase",
                       bootstyle="toolbutton-outline").pack(side=LEFT, padx=3)

        r1 = tb.Frame(cfg_inner); r1.pack(fill=X, pady=4)
        tb.Label(r1, text="笔刷大小:", width=10, anchor=W).pack(side=LEFT)
        tb.Scale(r1, from_=4, to=120, variable=self.brush_size, orient=HORIZONTAL,
                 command=lambda _=None: self.render_preview()).pack(side=LEFT, fill=X, expand=YES)
        self.brush_lbl = tb.Label(r1, text="22 px", width=8)
        self.brush_lbl.pack(side=LEFT)
        self.brush_size.trace_add("write", lambda *_: self.brush_lbl.configure(
            text=f"{self.brush_size.get()} px"))

        r2 = tb.Frame(cfg_inner); r2.pack(fill=X, pady=4)
        tb.Label(r2, text="画笔硬度:", width=10, anchor=W).pack(side=LEFT)
        tb.Scale(r2, from_=0, to=100, variable=self.brush_hardness, orient=HORIZONTAL).pack(
            side=LEFT, fill=X, expand=YES)
        self.hard_lbl = tb.Label(r2, text="60%", width=8)
        self.hard_lbl.pack(side=LEFT)
        self.brush_hardness.trace_add("write", lambda *_: self.hard_lbl.configure(
            text=f"{self.brush_hardness.get()}%"))

        r3 = tb.Frame(cfg_inner); r3.pack(fill=X, pady=4)
        tb.Label(r3, text="修复强度:", width=10, anchor=W).pack(side=LEFT)
        tb.Scale(r3, from_=1, to=20, variable=self.strength, orient=HORIZONTAL).pack(
            side=LEFT, fill=X, expand=YES)
        self.str_lbl = tb.Label(r3, text="7", width=8)
        self.str_lbl.pack(side=LEFT)
        self.strength.trace_add("write", lambda *_: self.str_lbl.configure(
            text=str(self.strength.get())))

        r4 = tb.Frame(cfg_inner); r4.pack(fill=X, pady=4)
        tb.Label(r4, text="输出格式:", width=10, anchor=W).pack(side=LEFT)
        for lab, val in [("PNG", "png"), ("JPG", "jpg"), ("WEBP", "webp")]:
            tb.Radiobutton(r4, text=lab, variable=self.output_format, value=val,
                           bootstyle="toolbutton-outline").pack(side=LEFT, padx=3)

        r4b = tb.Frame(cfg_inner); r4b.pack(fill=X, pady=4)
        tb.Label(r4b, text="修复模式:", width=10, anchor=W).pack(side=LEFT)
        tb.Radiobutton(r4b, text="本地AI", variable=self.repair_mode, value="local",
                       bootstyle="toolbutton-outline").pack(side=LEFT, padx=3)
        tb.Radiobutton(r4b, text="云端AI", variable=self.repair_mode, value="ai",
                       bootstyle="toolbutton-outline").pack(side=LEFT, padx=3)
        tb.Radiobutton(r4b, text="快速", variable=self.repair_mode, value="fast",
                       bootstyle="toolbutton-outline").pack(side=LEFT, padx=3)

        # 显示当前可用后端
        backend_info = get_local_backend_info()
        self._backend_lbl = tb.Label(cfg_inner,
            text=f"本地后端：{backend_info}",
            bootstyle="info", font=("微软雅黑", 8))
        self._backend_lbl.pack(anchor=W, pady=(0, 2))

        r5 = tb.Frame(cfg_inner); r5.pack(fill=X, pady=4)
        tb.Checkbutton(r5, text="显示蒙版覆盖", variable=self.show_mask,
                       bootstyle="round-toggle", command=self.render_preview).pack(side=LEFT)
        tb.Checkbutton(r5, text="分屏对比", variable=self.compare_mode,
                       bootstyle="round-toggle", command=self.render_preview).pack(side=LEFT, padx=10)

        # Batch mask option
        r6 = tb.Frame(cfg_inner); r6.pack(fill=X, pady=4)
        tb.Checkbutton(r6, text="批量时复用此蒙版位置", variable=self.batch_apply_mask,
                       bootstyle="round-toggle").pack(side=LEFT)

        # Actions
        act_box, act = make_card(left, "快捷操作", "AI去水印与常用工具")

        self.ai_btn = tb.Button(act, text="✦ AI一键去水印", bootstyle="success",
                                command=self.run_ai_remove, width=22)
        self.ai_btn.pack(fill=X, pady=3)
        self.doubao_btn = tb.Button(act, text="去豆包角标", bootstyle="info",
                                    command=self.run_doubao_remove, width=22)
        self.doubao_btn.pack(fill=X, pady=3)

        make_secondary_button(act, "预览修复效果  Space", self.preview_repair).pack(fill=X, pady=3)
        make_secondary_button(act, "撤销  Ctrl+Z", self.undo).pack(fill=X, pady=3)
        make_secondary_button(act, "重做  Ctrl+Y", self.redo).pack(fill=X, pady=3)
        make_secondary_button(act, "清空蒙版  Ctrl+L", self.clear_mask).pack(fill=X, pady=3)
        make_primary_button(act, "保存结果  Ctrl+S", self.save_result).pack(fill=X, pady=3)

        tb.Button(act, text="批量去水印", bootstyle="warning",
                  command=self.batch_remove, width=22).pack(fill=X, pady=(12, 3))

        # Help
        help_box, help_inner = make_card(left, "使用说明", "快速上手")
        tb.Label(
            help_inner,
            text=(
                "① 载入图片\n"
                "② 在图上涂抹水印区域（红色高亮）\n"
                "③ 选择修复模式后点「AI一键去水印」\n"
                "④ 确认效果后保存\n\n"
                "模式说明：\n"
                "• 本地AI：CUDA生成式填充，无需联网\n"
                "• 云端AI：调用 Claude API，需 Key\n"
                "• 快速：纯OpenCV，速度最快\n\n"
                "本地AI默认使用 CUDA 生成式填充，不再依赖 lama-cleaner。\n\n"
                "快捷键：Ctrl+Z/Y/S/L，Space预览"
                "快捷键：Ctrl+Z/Y/S/L，Space预览"
            ),
            justify=LEFT, wraplength=240, bootstyle="secondary"
        ).pack(anchor=W)

        # History
        hist_box, hist_inner = make_card(left, "操作历史", "")
        hist_box.pack(fill=BOTH, expand=YES)
        hist_inner.pack(fill=BOTH, expand=YES)
        self.history_list = tk.Listbox(hist_inner, height=8)
        self.history_list.pack(fill=BOTH, expand=YES)

        # Canvas workspace
        preview_box = tb.LabelFrame(right, text="AI去水印工作台")
        preview_box.pack(fill=BOTH, expand=YES)
        preview_inner = tb.Frame(preview_box, padding=10)
        preview_inner.pack(fill=BOTH, expand=YES)

        self.canvas = tk.Canvas(preview_inner, bg="#1f2430",
                                highlightthickness=1, highlightbackground="#3b4252",
                                cursor="crosshair")
        self.canvas.pack(fill=BOTH, expand=YES)
        self.canvas.bind("<Configure>", self.render_preview)
        self.canvas.bind("<ButtonPress-1>", self.start_paint)
        self.canvas.bind("<B1-Motion>", self.paint_move)
        self.canvas.bind("<ButtonRelease-1>", self.end_paint)
        # 拖拽支持：拖图片到输入框或画布均可加载
        bind_drop_to_widget(self.input_entry, lambda p: self.input_path.set(p), accept='image')
        bind_drop_to_widget(self.canvas,      lambda p: self.input_path.set(p), accept='image')

        # Status bar
        self.status_lbl = tb.Label(preview_inner,
                                   text="请载入图片，然后涂抹水印区域。",
                                   bootstyle="secondary")
        self.status_lbl.pack(fill=X, pady=(8, 0))

        # AI progress bar (hidden until running)
        self.ai_progress = tb.Progressbar(preview_inner, bootstyle="success-striped",
                                          mode="indeterminate", length=300)

    # ── API Key helpers ───────────────────────────────────────────────

    def _toggle_key_visibility(self):
        cur = self._api_key_entry.cget("show")
        self._api_key_entry.configure(show="" if cur == "*" else "*")

    def _save_api_key_ui(self):
        key = self._api_key_var.get().strip()
        if not key:
            messagebox.showwarning("提示", "请先输入 API Key")
            return
        if not key.startswith("sk-ant-"):
            if not messagebox.askyesno("警告", "Key 格式看起来不对（应以 sk-ant- 开头），确定保存？"):
                return
        _save_api_key(key)
        self._refresh_key_status()
        messagebox.showinfo("✅ 已保存", "API Key 已保存到本地，下次启动自动加载。\n现在可以使用「AI精细」模式了。")

    def _clear_api_key_ui(self):
        _save_api_key("")
        self._api_key_var.set("")
        self._refresh_key_status()

    def _refresh_key_status(self):
        key = _get_api_key()
        if key and key.startswith("sk-ant-"):
            self._key_status_lbl.configure(text="✅ Key 已配置", bootstyle="success")
        elif key:
            self._key_status_lbl.configure(text="⚠ Key 格式异常", bootstyle="warning")
        else:
            self._key_status_lbl.configure(text="❌ 未配置", bootstyle="danger")

    # ── Shortcuts ────────────────────────────────────────────────────

    def bind_shortcuts(self):
        self.parent_frame.bind_all("<Control-z>", lambda e: self.undo())
        self.parent_frame.bind_all("<Control-y>", lambda e: self.redo())
        self.parent_frame.bind_all("<Control-s>", lambda e: self.save_result())
        self.parent_frame.bind_all("<Control-l>", lambda e: self.clear_mask())
        self.parent_frame.bind_all("<space>", lambda e: self.preview_repair())

    # ── History ──────────────────────────────────────────────────────

    def add_history(self, text):
        self.history_records.insert(0, text)
        self.history_records = self.history_records[:50]
        self.history_list.delete(0, "end")
        for item in self.history_records:
            self.history_list.insert("end", item)

    # ── Undo / Redo ──────────────────────────────────────────────────

    def push_undo(self):
        if self.mask_image is not None:
            self.undo_stack.append(self.mask_image.copy())
            self.undo_stack = self.undo_stack[-40:]
            self.redo_stack.clear()

    def undo(self):
        if not self.undo_stack or self.mask_image is None:
            return
        self.redo_stack.append(self.mask_image.copy())
        self.mask_image = self.undo_stack.pop()
        self.repaired_image = None
        self.add_history("撤销")
        self.render_preview()

    def redo(self):
        if not self.redo_stack or self.mask_image is None:
            return
        self.undo_stack.append(self.mask_image.copy())
        self.mask_image = self.redo_stack.pop()
        self.repaired_image = None
        self.add_history("重做")
        self.render_preview()

    # ── Input changed ─────────────────────────────────────────────────

    def on_input_changed(self, *_):
        self.output_dir.set(default_output_dir(self.input_path.get()))
        p = Path(self.input_path.get())
        if p.exists() and p.is_file():
            try:
                self.original_image = open_image_with_exif(p).convert("RGB")
                self.mask_image = Image.new("L", self.original_image.size, 0)
                self.repaired_image = None
                self._cached_disp = None  # 清除缓存
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.add_history(f"载入：{p.name}")
                self.render_preview()
                self.status_lbl.configure(
                    text=f"已加载：{p.name}  |  {self.original_image.width} × {self.original_image.height}")
            except Exception as e:
                self.status_lbl.configure(text=f"加载失败：{e}")
        else:
            self.original_image = None
            self.mask_image = None
            self.repaired_image = None
            self._cached_disp = None
            self.render_preview()

    # ── Canvas / Painting ─────────────────────────────────────────────

    def canvas_to_image_xy(self, cx, cy):
        if self.original_image is None:
            return 0, 0
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        dw = int(self.original_image.width * self.scale_ratio)
        dh = int(self.original_image.height * self.scale_ratio)
        ox = (cw - dw) // 2
        oy = (ch - dh) // 2
        ix = int((cx - ox) / max(self.scale_ratio, 1e-6))
        iy = int((cy - oy) / max(self.scale_ratio, 1e-6))
        ix = max(0, min(self.original_image.width - 1, ix))
        iy = max(0, min(self.original_image.height - 1, iy))
        return ix, iy

    def _brush_patch(self, radius):
        size = radius * 2 + 1
        patch = Image.new("L", (size, size), 0)
        draw = ImageDraw.Draw(patch)
        draw.ellipse((0, 0, size - 1, size - 1), fill=255)
        hardness = max(0, min(100, self.brush_hardness.get()))
        if hardness < 100:
            blur = max(0, int((100 - hardness) / 8))
            if blur > 0:
                patch = patch.filter(ImageFilter.GaussianBlur(radius=blur))
        return patch

    def _canvas_brush_color(self):
        return "#ff3232" if self.tool_mode.get() == "paint" else "#ffffff"

    def _canvas_brush_radius(self):
        """把图像坐标系的笔刷半径转换为 canvas 坐标系"""
        return max(2, int(self.brush_size.get() * self.scale_ratio))

    def _draw_brush_on_canvas(self, cx, cy):
        """直接在 canvas 上画一个半透明圆圈，不触碰 PIL，极速响应"""
        r = self._canvas_brush_radius()
        color = _BRUSH_COLORS[self.tool_mode.get()]
        # 用 stipple 模拟半透明（tkinter 原生不支持真透明）
        self.canvas.create_oval(
            cx - r, cy - r, cx + r, cy + r,
            fill=color, outline="", stipple="gray50",
            tags="brush_stroke"
        )

    def paint_at(self, x, y):
        """更新 PIL 蒙版（图像坐标系），不触发 render_preview"""
        if self.mask_image is None:
            return
        radius = self.brush_size.get()
        patch = self._brush_patch(radius)
        box = (x - radius, y - radius)
        if self.tool_mode.get() == "erase":
            temp = Image.new("L", self.mask_image.size, 0)
            temp.paste(patch, box)
            self.mask_image = ImageChops.subtract(self.mask_image, temp)
        else:
            self.mask_image.paste(255, box=box, mask=patch)

    def paint_line(self, x1, y1, x2, y2, cx1, cy1, cx2, cy2):
        """在图像坐标更新蒙版，同时在 canvas 坐标画笔迹"""
        steps = max(abs(x2 - x1), abs(y2 - y1), 1)
        for i in range(steps + 1):
            t = i / steps
            ix = int(x1 + (x2 - x1) * t)
            iy = int(y1 + (y2 - y1) * t)
            cx = int(cx1 + (cx2 - cx1) * t)
            cy = int(cy1 + (cy2 - cy1) * t)
            self.paint_at(ix, iy)
            self._draw_brush_on_canvas(cx, cy)

    def start_paint(self, event):
        if self.original_image is None:
            return
        self.repaired_image = None
        self.push_undo()
        self.last_x, self.last_y = self.canvas_to_image_xy(event.x, event.y)
        self.last_cx, self.last_cy = event.x, event.y
        self.paint_at(self.last_x, self.last_y)
        self._draw_brush_on_canvas(event.x, event.y)

    def paint_move(self, event):
        if self.original_image is None:
            return
        x, y = self.canvas_to_image_xy(event.x, event.y)
        self.paint_line(self.last_x, self.last_y, x, y,
                        self.last_cx, self.last_cy, event.x, event.y)
        self.last_x, self.last_y = x, y
        self.last_cx, self.last_cy = event.x, event.y

    def end_paint(self, _=None):
        self.last_x = self.last_y = None
        self.last_cx = self.last_cy = None
        self.add_history("涂抹笔画完成")
        # 松手后才做一次完整的预览刷新
        self.render_preview()

    def clear_mask(self):
        if self.original_image is None:
            return
        self.mask_image = Image.new("L", self.original_image.size, 0)
        self.repaired_image = None
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.add_history("清空蒙版")
        self.render_preview()

    # ── Render ───────────────────────────────────────────────────────

    def _invalidate_cache(self):
        self._cached_disp = None
        self._cached_disp_size = None

    def render_preview(self, _event=None):
        self.canvas.delete("all")
        if self.original_image is None:
            self.canvas.create_text(200, 120, text="暂无预览", fill="#888888", font=("微软雅黑", 14))
            return

        cw = max(120, self.canvas.winfo_width() or 800)
        ch = max(120, self.canvas.winfo_height() or 600)

        if self.compare_mode.get() and self.repaired_image is not None:
            self._render_split(cw, ch)
            return

        base = self.repaired_image if self.repaired_image else self.original_image
        ratio = min((cw - 20) / base.width, (ch - 20) / base.height, 1.0)
        ratio = max(ratio, 0.01)
        self.scale_ratio = ratio
        target_size = (max(1, int(base.width * ratio)), max(1, int(base.height * ratio)))

        # 缓存底图缩放结果，窗口尺寸不变就直接复用
        if (not hasattr(self, '_cached_disp') or
                self._cached_disp is None or
                getattr(self, '_cached_disp_size', None) != target_size or
                getattr(self, '_cached_disp_base', None) is not base):
            self._cached_disp = base.resize(target_size, Image.Resampling.LANCZOS)
            self._cached_disp_size = target_size
            self._cached_disp_base = base

        disp = self._cached_disp.copy()

        # 蒙版叠加：用 NEAREST 缩放（快），只在有蒙版时才合成
        if self.mask_image is not None and self.repaired_image is None and self.show_mask.get():
            # 用 numpy 做快速合成（有 cv2 时）
            if HAS_CV2:
                import numpy as np
                disp_arr = np.array(disp, dtype=np.float32)
                msk_small = np.array(
                    self.mask_image.resize(target_size, Image.Resampling.NEAREST),
                    dtype=np.float32) / 255.0
                red = np.array([255, 50, 50], dtype=np.float32)
                alpha = msk_small[:, :, np.newaxis] * 0.5
                disp_arr = disp_arr * (1 - alpha) + red * alpha
                disp = Image.fromarray(np.clip(disp_arr, 0, 255).astype(np.uint8))
            else:
                msk_small = self.mask_image.resize(target_size, Image.Resampling.NEAREST)
                red_layer = Image.new("RGBA", target_size, (255, 50, 50, 0))
                red_layer.putalpha(msk_small.point(lambda v: min(130, v)))
                base_rgba = disp.convert("RGBA")
                base_rgba.alpha_composite(red_layer)
                disp = base_rgba.convert("RGB")

        self.tk_preview = ImageTk.PhotoImage(disp)
        self.canvas.create_image(cw // 2, ch // 2, image=self.tk_preview, anchor="center")

    def _render_split(self, cw, ch):
        half = max(60, cw // 2 - 6)
        imgs = [self.original_image, self.repaired_image]
        rendered = []
        for img in imgs:
            ratio = min((half - 10) / img.width, (ch - 20) / img.height, 1.0)
            ratio = max(ratio, 0.01)
            self.scale_ratio = ratio
            rendered.append(img.resize((max(1, int(img.width * ratio)),
                                        max(1, int(img.height * ratio))),
                                       Image.Resampling.LANCZOS))
        self.tk_preview_left = ImageTk.PhotoImage(rendered[0])
        self.tk_preview_right = ImageTk.PhotoImage(rendered[1])
        self.canvas.create_image(cw // 4, ch // 2, image=self.tk_preview_left, anchor="center")
        self.canvas.create_image(cw * 3 // 4, ch // 2, image=self.tk_preview_right, anchor="center")
        self.canvas.create_line(cw // 2, 10, cw // 2, ch - 10, fill="#888888", dash=(4, 2))
        self.canvas.create_text(cw // 4, 18, text="原图", fill="#aaaaaa", font=("微软雅黑", 10))
        self.canvas.create_text(cw * 3 // 4, 18, text="去水印后", fill="#aaaaaa", font=("微软雅黑", 10))

    # ── Core repair ──────────────────────────────────────────────────

    def _repair_image_with_mode(self, orig, mask, mode, progress_cb=None):
        if orig is None or mask is None:
            return None
        if max(mask.getdata()) < 10:
            return None

        orig = orig.convert("RGB")

        if mode == "fast":
            if progress_cb:
                progress_cb("快速修复中（OpenCV TELEA+NS 融合）…")
            return _classical_inpaint(orig, mask, strength=self.strength.get())

        if mode == "local":
            return local_inpaint(
                orig, mask,
                strength=self.strength.get(),
                progress_cb=progress_cb
            )

        return ai_inpaint_via_claude(
            orig, mask,
            strength=self.strength.get(),
            progress_cb=progress_cb
        )

    def _do_doubao_repair(self, progress_cb=None):
        if self.original_image is None or self.mask_image is None:
            return None
        if max(self.mask_image.getdata()) < 10:
            return None
        return remove_doubao_watermark(
            self.original_image.convert("RGB"),
            self.mask_image,
            strength=self.strength.get(),
            progress_cb=progress_cb,
        )

    def _do_repair(self, progress_cb=None):
        return self._repair_image_with_mode(
            self.original_image,
            self.mask_image,
            self.repair_mode.get(),
            progress_cb=progress_cb,
        )

    def preview_repair(self):
        if self.original_image is None:
            messagebox.showwarning("提示", "请先加载图片")
            return
        result = self._do_repair()
        if result is None:
            messagebox.showwarning("提示", "请先涂抹水印区域")
            return
        self.repaired_image = result
        self.add_history("预览修复效果")
        self.render_preview()
        self.status_lbl.configure(text="预览完成，可勾选「分屏对比」查看前后效果。")

    # ── AI button (async) ─────────────────────────────────────────────

    def _start_repair_job(self, job_key, worker_fn, status_text):
        if self._ai_running:
            return
        if self.original_image is None:
            messagebox.showwarning("提示", "请先加载图片")
            return
        if self.mask_image is None or max(self.mask_image.getdata()) < 10:
            messagebox.showwarning("提示", "请先在图上涂抹需要处理的区域")
            return

        self._ai_running = True
        self.ai_btn.configure(state="disabled")
        if hasattr(self, "doubao_btn"):
            self.doubao_btn.configure(state="disabled")
        if job_key == "doubao" and hasattr(self, "doubao_btn"):
            self.doubao_btn.configure(text="处理中…")
        else:
            self.ai_btn.configure(text="处理中…")
        self.ai_progress.pack(fill=X, pady=(4, 0))
        self.ai_progress.start(12)
        self.status_lbl.configure(text=status_text)

        def worker():
            def cb(msg):
                try:
                    self.status_lbl.configure(text=msg)
                except Exception:
                    pass
            result = worker_fn(progress_cb=cb)
            self.parent_frame.after(0, lambda: self._repair_done(job_key, result))

        threading.Thread(target=worker, daemon=True).start()

    def _repair_done(self, job_key, result):
        self._ai_running = False
        self.ai_progress.stop()
        self.ai_progress.pack_forget()
        self.ai_btn.configure(state="normal", text="✦ AI一键去水印")
        if hasattr(self, "doubao_btn"):
            self.doubao_btn.configure(state="normal", text="去豆包角标")
        if result is None:
            self.status_lbl.configure(text="修复失败，请检查涂抹区域后重试。")
            return
        self.repaired_image = result
        self._saved_mask = self.mask_image.copy()
        self.add_history("豆包角标去除完成" if job_key == "doubao" else "AI去水印完成")
        self.render_preview()
        self.status_lbl.configure(
            text="✅ 豆包角标去除完成，可查看前后效果并保存。"
            if job_key == "doubao"
            else "✅ AI去水印完成！可勾选分屏对比查看前后效果，确认后保存。"
        )

    def run_doubao_remove(self):
        self._start_repair_job(
            "doubao",
            self._do_doubao_repair,
            "豆包角标专项修复中…",
        )

    def run_ai_remove(self):
        mode = self.repair_mode.get()
        mode_labels = {
            "fast": "快速修复中（OpenCV 双算法）…",
            "local": f"本地AI修复中（{get_local_backend_info()}）…",
            "ai": "Step 1/3：OpenCV 初步修复中…",
        }
        self._start_repair_job(
            "general",
            self._do_repair,
            mode_labels.get(mode, "修复中…"),
        )

    def _ai_done(self, result):
        self._repair_done("general", result)

    # ?? Save ─────────────────────────────────────────────────────────

    def _do_save(self, img: Image.Image, src_path: Path):
        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        output_base.mkdir(parents=True, exist_ok=True)
        out = output_base / f"{src_path.stem}_no_watermark.{self.output_format.get()}"
        return save_image_by_format(img, out, self.output_format.get())

    def save_result(self):
        if self.original_image is None:
            messagebox.showwarning("提示", "请先加载图片")
            return
        result = self.repaired_image
        if result is None:
            result = self._do_repair()
        if result is None:
            messagebox.showwarning("提示", "请先涂抹水印区域并执行修复")
            return

        src = Path(self.input_path.get())
        progress = self.create_progress_window("保存去水印结果…", 1)
        self.update_progress(progress, 0, 1, src.name)
        saved = self._do_save(result, src)
        progress.output_dir = str(saved.parent)
        self.add_history(f"已保存：{saved.name}")
        self.finish_processing(progress, 1, [], "AI去水印", f"输出文件: {saved.name}")

    # ── Batch ─────────────────────────────────────────────────────────

    def batch_remove(self):
        if not self.batch_apply_mask.get() or self._saved_mask is None:
            messagebox.showinfo(
                "批量去水印",
                "请先：\n1. 在单张图上涂抹水印区域\n2. 执行「AI一键去水印」\n3. 勾选「批量时复用此蒙版位置」\n4. 再点「批量去水印」"
            )
            return

        p = Path(self.input_path.get())
        images = list_images(p if p.is_dir() else p.parent, self.include_subdirs.get())
        if not images:
            messagebox.showwarning("提示", "没有找到图片")
            return

        output_base = Path(self.output_dir.get() or default_output_dir(self.input_path.get()))
        progress = self.create_progress_window("批量去水印中…", len(images))
        progress.output_dir = str(output_base)
        processed, failed = 0, []

        saved_mask = self._saved_mask

        for i, (img_path, rel_path) in enumerate(images):
            try:
                self.update_progress(progress, i, len(images), str(rel_path))
                img = open_image_with_exif(img_path).convert("RGB")
                # Resize mask to match current image if sizes differ
                if img.size != saved_mask.size:
                    msk = saved_mask.resize(img.size, Image.Resampling.LANCZOS)
                else:
                    msk = saved_mask
                result = self._repair_image_with_mode(img, msk, self.repair_mode.get())
                out_path = (output_base / rel_path).with_stem(rel_path.stem + "_no_watermark")
                save_image_by_format(result, out_path, self.output_format.get())
                processed += 1
            except Exception as e:
                failed.append(f"{rel_path} - {e}")

        self.finish_processing(progress, processed, failed, "批量AI去水印",
                               f"处理图片数: {processed}")
