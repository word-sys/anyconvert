"""
Image extraction and alpha/smask compositing engine for anyconvert.
Extracts embedded images from PDF pages with full color fidelity and transparency.
"""

import io
from typing import List, Optional, Tuple

from PIL import Image
import pymupdf

from anyconvert.core.models import ImageBlock, Rect


def extract_rgba_image_bytes(doc: pymupdf.Document, xref: int) -> Optional[Tuple[bytes, str, int, int]]:
    """
    Extract an image by xref, compositing alpha/smask if present and converting CMYK to sRGB.

    Returns:
        Tuple of (image_bytes, format_ext, width, height) or None if extraction fails.
    """
    try:
        image_data = doc.extract_image(xref)
        if not image_data or "image" not in image_data:
            return None

        smask_xref = image_data.get("smask", 0)
        if not smask_xref:
            try:
                smask_val = doc.xref_get_key(xref, "SMask")
                if smask_val and smask_val[0] == "xref":
                    smask_xref = int(smask_val[1].split()[0])
            except Exception:
                pass

        base_pix = pymupdf.Pixmap(doc, xref)

        if smask_xref and smask_xref > 0:
            try:
                mask_pix = pymupdf.Pixmap(doc, smask_xref)
                if base_pix.n != 3:
                    base_pix = pymupdf.Pixmap(pymupdf.csRGB, base_pix)
                if mask_pix.n != 1:
                    mask_pix = pymupdf.Pixmap(pymupdf.csGRAY, mask_pix)

                if base_pix.width == mask_pix.width and base_pix.height == mask_pix.height:
                    rgba_pix = pymupdf.Pixmap(base_pix, mask_pix)
                    return (rgba_pix.tobytes("png"), "png", base_pix.width, base_pix.height)
                else:
                    base_img = Image.open(io.BytesIO(base_pix.tobytes("png"))).convert("RGB")
                    mask_img = Image.open(io.BytesIO(mask_pix.tobytes("png"))).convert("L")
                    mask_img = mask_img.resize(base_img.size, Image.Resampling.LANCZOS)
                    base_img.putalpha(mask_img)

                    out_buf = io.BytesIO()
                    base_img.save(out_buf, format="PNG")
                    return (out_buf.getvalue(), "png", base_img.width, base_img.height)
            except Exception:
                pass

        if base_pix.alpha:
            if base_pix.n != 4:
                base_pix = pymupdf.Pixmap(pymupdf.csRGB, base_pix)
            return (base_pix.tobytes("png"), "png", base_pix.width, base_pix.height)

        if base_pix.n >= 4:
            rgb_pix = pymupdf.Pixmap(pymupdf.csRGB, base_pix)
            return (rgb_pix.tobytes("png"), "png", base_pix.width, base_pix.height)

        raw_bytes = image_data["image"]
        ext = image_data.get("ext", "png").lower()
        width = image_data.get("width", base_pix.width)
        height = image_data.get("height", base_pix.height)
        return (raw_bytes, ext, width, height)

    except Exception:
        return None


def extract_page_images(doc: pymupdf.Document, page: pymupdf.Page) -> List[ImageBlock]:
    """
    Extract all placed images on a page with their spatial bounding boxes.
    """
    image_blocks: List[ImageBlock] = []
    seen_xrefs = set()

    try:
        image_info_list = page.get_image_info(xrefs=True)
    except Exception:
        image_info_list = []

    for img_info in image_info_list:
        xref = img_info.get("xref", 0)
        bbox = img_info.get("bbox")

        if not xref or not bbox:
            continue

        r = pymupdf.Rect(bbox)
        if r.is_empty or not r.is_valid:
            continue

        rect_model = Rect(r.x0, r.y0, r.x1, r.y1)
        res = extract_rgba_image_bytes(doc, xref)
        if not res:
            continue

        img_bytes, ext, w, h = res
        image_blocks.append(
            ImageBlock(
                bbox=rect_model,
                image_bytes=img_bytes,
                image_format=ext,
                width=w,
                height=h,
            )
        )
        seen_xrefs.add(xref)

    # Fallback for images not returned by get_image_info
    try:
        raw_images = page.get_images(full=True)
        for img_tuple in raw_images:
            xref = img_tuple[0]
            if xref in seen_xrefs:
                continue
            rects = page.get_image_rects(xref)
            for r in rects:
                if r.is_empty or not r.is_valid:
                    continue
                res = extract_rgba_image_bytes(doc, xref)
                if not res:
                    continue
                img_bytes, ext, w, h = res
                image_blocks.append(
                    ImageBlock(
                        bbox=Rect(r.x0, r.y0, r.x1, r.y1),
                        image_bytes=img_bytes,
                        image_format=ext,
                        width=w,
                        height=h,
                    )
                )
                seen_xrefs.add(xref)
    except Exception:
        pass

    return image_blocks
