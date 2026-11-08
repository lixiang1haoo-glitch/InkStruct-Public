"""Bounded, embedded raster references. Rendering never reads paths or URLs."""

import base64
import io
import math
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from PIL import Image, ImageOps

from .schema import Diagnostic

MAX_BYTES = 8_000_000
MAX_PIXELS = 2_000_000
MAX_IMAGE_RESOURCES = 64
MAX_IMAGE_CATALOG_BYTES = 128_000_000
WINDOWS_RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL',
                          *(f'COM{i}' for i in range(1, 10)),
                          *(f'LPT{i}' for i in range(1, 10))}


def local_raster_reference_name(source: str) -> str | None:
    """Identify supported missing local raster references without reading a file.

    Decode once, exactly as import does. Unknown types, remote URLs and ambiguous
    or unsafe Windows paths cannot opt into omission just by ending in .png.
    """
    try:
        if not isinstance(source, str) or any(ord(c) < 32 for c in source):
            return None
        url = urlsplit(source)
        if not source or url.scheme or url.netloc or url.query or url.fragment:
            return None
        if re.search(r'%(?![0-9a-fA-F]{2})', url.path):
            return None
        decoded = unquote(url.path, errors='strict').replace('\\', '/')
        parts = decoded.split('/')
        if (decoded.startswith('/') or any(p in {'', '..'} for p in parts)
                or any(ord(c) < 32 or c in ':<>|"?*' for c in decoded)
                or any(p != '.' and p.endswith((' ', '.')) for p in parts)
                or any(p.split('.')[0].upper() in WINDOWS_RESERVED_NAMES for p in parts)):
            return None
        path = PurePosixPath(decoded)
        return path.name if path.suffix.lower() in {'.png', '.jpg', '.jpeg'} else None
    except (ValueError, UnicodeError, TypeError):
        return None


def decoded_image(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("Image exceeds the 8 MB resource limit")
    try:
        with Image.open(io.BytesIO(raw)) as image:
            if image.format not in {"PNG", "JPEG"}:
                raise ValueError("Raster references support PNG and JPEG only")
            if image.width * image.height > MAX_PIXELS or getattr(image, "n_frames", 1) != 1:
                raise ValueError("Image must be a single frame of at most 2 million pixels")
            return ImageOps.exif_transpose(image).convert("RGBA")
    except Image.DecompressionBombError as error:
        raise ValueError("Image exceeds pixel budget") from error


@dataclass(frozen=True)
class RasterResource:
    source: str
    original_sha256: str
    original_base64: str
    png_sha256: str
    png_base64: str
    width_px: int
    height_px: int
    schema_version: str = "inkstruct_raster_reference_v1"

    def __post_init__(self):
        if (
            not isinstance(self.source, str)
            or not self.source
            or self.schema_version != "inkstruct_raster_reference_v1"
        ):
            raise ValueError("Invalid raster reference identity")
        if any(
            not isinstance(v, str) or len(v) > 12_000_000
            for v in (self.original_base64, self.png_base64)
        ):
            raise ValueError("Raster data exceeds its resource budget")
        raw = base64.b64decode(self.original_base64, validate=True)
        preview = base64.b64decode(self.png_base64, validate=True)
        if (
            sha256(raw).hexdigest() != self.original_sha256
            or sha256(preview).hexdigest() != self.png_sha256
        ):
            raise ValueError("Raster reference hash mismatch")
        original = decoded_image(raw)
        try:
            with Image.open(io.BytesIO(preview)) as png:
                if png.format != "PNG" or png.size != original.size:
                    raise ValueError("Raster preview format or dimensions differ from original")
                if png.convert("RGBA").tobytes() != original.tobytes():
                    raise ValueError("Raster preview pixels differ from original")
        except Image.DecompressionBombError as error:
            raise ValueError("Raster preview exceeds pixel budget") from error
        if (
            type(self.width_px) is not int
            or type(self.height_px) is not int
            or original.size != (self.width_px, self.height_px)
        ):
            raise ValueError("Raster dimensions differ from the image")

    @property
    def aspect_ratio(self):
        return self.height_px / self.width_px

    @classmethod
    def from_file(cls, path, source):
        path = Path(path)
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Image exceeds the 8 MB resource limit")
        raw = path.read_bytes()
        image = decoded_image(raw)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        png = buffer.getvalue()
        return cls(
            source,
            sha256(raw).hexdigest(),
            base64.b64encode(raw).decode("ascii"),
            sha256(png).hexdigest(),
            base64.b64encode(png).decode("ascii"),
            image.width,
            image.height,
        )


@dataclass(frozen=True)
class ImageStyle:
    width_mm: float = 80
    max_height_mm: float | None = None
    caption_gap_mm: float = 2
    align: str = "center"
    svg_tolerance_mm: float = 0.05
    schema_version: str = "inkstruct_image_style_v1"
    height_mm: float | None = None

    def __post_init__(self):
        if self.schema_version not in {"inkstruct_image_style_v1", "inkstruct_image_style_v2"}:
            raise ValueError("Invalid image style version")
        if self.height_mm is not None:
            if not math.isfinite(self.height_mm) or not 0 < self.height_mm <= 2000:
                raise ValueError("Image height must be within (0, 2000] mm")
            object.__setattr__(self, "schema_version", "inkstruct_image_style_v2")
        if not math.isfinite(self.svg_tolerance_mm) or not 0.001 <= self.svg_tolerance_mm <= 1:
            raise ValueError("SVG tolerance must be within 0.001–1 mm")
        if not math.isfinite(self.width_mm) or not 0 < self.width_mm <= 2000:
            raise ValueError("Image width must be within (0, 2000] mm")
        if self.max_height_mm is not None and (
            not math.isfinite(self.max_height_mm) or not 0 < self.max_height_mm <= 2000
        ):
            raise ValueError("Image height limit must be within (0, 2000] mm")
        if not math.isfinite(self.caption_gap_mm) or not 0 <= self.caption_gap_mm <= 100:
            raise ValueError("Image caption gap must be within 0–100 mm")
        if (
            self.align not in {"left", "center", "right"}
        ):
            raise ValueError("Invalid image style")

    def dimensions(self, resource):
        ratio = resource.aspect_ratio if resource else 0.5
        height = self.height_mm if self.height_mm is not None else self.width_mm * ratio
        width = height / ratio if self.height_mm is not None else self.width_mm
        if self.height_mm is None and self.max_height_mm is not None and height > self.max_height_mm:
            height = self.max_height_mm
            width = height / ratio
        return width, height


def import_local_images(document, flow, root):
    """Import relative files within an explicitly selected root, without networking."""
    root = Path(root).resolve()
    resources = {r.source: r for r in flow.images}
    def encoded_size(resource):
        return len(resource.original_base64) + len(getattr(resource, "png_base64", ""))

    catalog_size = sum(map(encoded_size, resources.values()))
    issues = []
    for node in (n for top in document.nodes for n in top.walk() if n.kind == "image"):
        source = dict(node.attributes).get("src", "")
        if source in resources:
            continue
        try:
            url = urlsplit(source)
            decoded = unquote(url.path, errors="strict")
            local = Path(decoded)
            if (
                url.scheme
                or url.netloc
                or url.query
                or url.fragment
                or local.is_absolute()
                or local.drive
                or any(ord(c) < 32 or c in ':<>|"?*' for c in decoded)
                or local.suffix.lower() not in {".png", ".jpg", ".jpeg", ".svg"}
                or not source
            ):
                raise ValueError(
                    "Import a local relative PNG/JPEG or single-line SVG, or explicitly attach a file in image settings"
                )
            file = (root / local).resolve()
            if not file.is_relative_to(root):
                raise ValueError("Image path escapes the selected image root")
            if len(resources) >= MAX_IMAGE_RESOURCES:
                raise ValueError("Image catalog exceeds 64 resources")
            resource = import_image_file(file, source)
            size = encoded_size(resource)
            if catalog_size + size > MAX_IMAGE_CATALOG_BYTES:
                raise ValueError("Image catalog exceeds its 128 MB encoded-data budget")
            resources[source] = resource
            catalog_size += size
        except FileNotFoundError as error:
            code = 'image-import-missing' if local_raster_reference_name(source) else 'image-import-failed'
            issues.append(Diagnostic(code, str(error), node.span))
        except (ValueError, OSError) as error:
            issues.append(Diagnostic("image-import-failed", str(error), node.span))
    return replace(flow, images=tuple(resources.values())), tuple(issues)


def import_image_file(path, source):
    from .line_svg import LineSvgResource

    resource_type = LineSvgResource if Path(path).suffix.lower() == ".svg" else RasterResource
    return resource_type.from_file(path, source)
