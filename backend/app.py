"""
书法字帖生成器 MVP - 后端服务
专注隶书（Clerical Script / Lishu）
"""
import io
import json
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdf_canvas

app = FastAPI(title="书法字帖生成器", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).parent.parent / "data"
CHAR_DIR = DATA_DIR / "characters" / "lishu"
FONT_DIR = DATA_DIR / "fonts"

# 字库元数据
CHAR_DB: dict[str, list[dict]] = {}


def load_char_db():
    """加载字库索引"""
    global CHAR_DB
    index_file = DATA_DIR / "lishu_index.json"
    if index_file.exists():
        with open(index_file, "r", encoding="utf-8") as f:
            CHAR_DB = json.load(f)


def get_lishu_font(size: int = 120) -> ImageFont.FreeTypeFont | None:
    """尝试加载隶书字体"""
    font_candidates = [
        FONT_DIR / "lishu.ttf",
        FONT_DIR / "lishu.otf",
        # macOS 系统自带隶书
        Path("/System/Library/Fonts/Supplemental/Baoli.ttc"),
        Path("/System/Library/Fonts/STHeiti Light.ttc"),
        Path("/Library/Fonts/Kaiti.ttc"),
    ]
    for fp in font_candidates:
        if fp.exists():
            try:
                return ImageFont.truetype(str(fp), size)
            except Exception:
                continue
    # fallback: 尝试系统中文字体
    system_fonts = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]
    for fp in system_fonts:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return None


def render_character(char: str, cell_size: int = 200, font_size: int = 150) -> Image.Image:
    """渲染单个字到图片"""
    img = Image.new("RGBA", (cell_size, cell_size), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)

    # 检查是否有碑帖切字图片
    char_images = list(CHAR_DIR.glob(f"{char}_*.png"))
    if char_images:
        char_img = Image.open(char_images[0]).convert("RGBA")
        char_img = char_img.resize((cell_size - 20, cell_size - 20), Image.LANCZOS)
        img.paste(char_img, (10, 10), char_img)
        return img

    # 否则用字体渲染
    font = get_lishu_font(font_size)
    if font:
        bbox = draw.textbbox((0, 0), char, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (cell_size - tw) // 2 - bbox[0]
        y = (cell_size - th) // 2 - bbox[1]
        draw.text((x, y), char, fill=(0, 0, 0, 255), font=font)
    else:
        # 最终 fallback
        draw.text((cell_size // 4, cell_size // 4), char, fill=(0, 0, 0, 255))

    return img


def draw_grid_cell(draw: ImageDraw.Draw, x: int, y: int, size: int,
                   grid_type: str = "mi", color=(200, 200, 200)):
    """绘制单个格子（米字格/田字格/九宫格）"""
    # 外框
    draw.rectangle([x, y, x + size, y + size], outline=(100, 100, 100), width=2)

    if grid_type == "mi":  # 米字格
        mid = size // 2
        # 十字
        draw.line([(x + mid, y), (x + mid, y + size)], fill=color, width=1)
        draw.line([(x, y + mid), (x + size, y + mid)], fill=color, width=1)
        # 对角线
        draw.line([(x, y), (x + size, y + size)], fill=color, width=1)
        draw.line([(x + size, y), (x, y + size)], fill=color, width=1)
    elif grid_type == "tian":  # 田字格
        mid = size // 2
        draw.line([(x + mid, y), (x + mid, y + size)], fill=color, width=1)
        draw.line([(x, y + mid), (x + size, y + mid)], fill=color, width=1)
    elif grid_type == "jiu":  # 九宫格
        t1, t2 = size // 3, size * 2 // 3
        draw.line([(x + t1, y), (x + t1, y + size)], fill=color, width=1)
        draw.line([(x + t2, y), (x + t2, y + size)], fill=color, width=1)
        draw.line([(x, y + t1), (x + size, y + t1)], fill=color, width=1)
        draw.line([(x, y + t2), (x + size, y + t2)], fill=color, width=1)


def generate_copybook_image(
    text: str,
    cols: int = 6,
    cell_size: int = 200,
    grid_type: str = "mi",
    mode: str = "normal",
) -> Image.Image:
    """生成字帖图片"""
    chars = [c for c in text if c.strip()]
    if not chars:
        chars = ["无"]

    rows = (len(chars) + cols - 1) // cols
    padding = 40
    title_height = 60
    width = cols * cell_size + padding * 2
    height = rows * cell_size + padding * 2 + title_height

    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    # 标题
    title_font = get_lishu_font(36)
    title = f"隶书字帖 · {grid_type_name(grid_type)}"
    if title_font:
        draw.text((padding, 15), title, fill=(80, 80, 80), font=title_font)
    else:
        draw.text((padding, 15), title, fill=(80, 80, 80))

    # 绘制格子和字
    for i, char in enumerate(chars):
        row, col = divmod(i, cols)
        x = padding + col * cell_size
        y = padding + title_height + row * cell_size

        # 画格子
        draw_grid_cell(draw, x, y, cell_size, grid_type)

        # 渲染字
        char_img = render_character(char, cell_size, int(cell_size * 0.75))

        if mode == "miaohong":  # 描红模式 - 浅色
            char_img = char_img.convert("RGBA")
            r, g, b, a = char_img.split()
            # 降低透明度实现描红效果
            a = a.point(lambda p: int(p * 0.15))
            char_img = Image.merge("RGBA", (r, g, b, a))
            # 将红色叠加
            red_layer = Image.new("RGBA", char_img.size, (200, 50, 50, 0))
            red_draw = ImageDraw.Draw(red_layer)
            img.paste(Image.alpha_composite(
                Image.new("RGBA", char_img.size, (255, 255, 255, 255)),
                char_img
            ).convert("RGB"), (x, y))
        else:
            composite = Image.alpha_composite(
                Image.new("RGBA", (cell_size, cell_size), (255, 255, 255, 255)),
                char_img,
            )
            img.paste(composite.convert("RGB"), (x, y))

        # 重新绘制格子线（覆盖在字上面）
        draw_grid_cell(draw, x, y, cell_size, grid_type, color=(210, 210, 210))

    return img


def grid_type_name(grid_type: str) -> str:
    return {"mi": "米字格", "tian": "田字格", "jiu": "九宫格"}.get(grid_type, "米字格")


@app.on_event("startup")
async def startup():
    load_char_db()


@app.get("/api/preview")
async def preview(
    text: str = Query(..., description="要生成字帖的文字"),
    cols: int = Query(6, ge=1, le=12),
    cell_size: int = Query(200, ge=100, le=400),
    grid_type: str = Query("mi", regex="^(mi|tian|jiu)$"),
    mode: str = Query("normal", regex="^(normal|miaohong)$"),
):
    """生成字帖预览图片"""
    img = generate_copybook_image(text, cols, cell_size, grid_type, mode)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")


@app.get("/api/pdf")
async def generate_pdf(
    text: str = Query(..., description="要生成字帖的文字"),
    cols: int = Query(6, ge=1, le=12),
    cell_size: int = Query(200, ge=100, le=400),
    grid_type: str = Query("mi", regex="^(mi|tian|jiu)$"),
    mode: str = Query("normal", regex="^(normal|miaohong)$"),
):
    """生成字帖PDF"""
    img = generate_copybook_image(text, cols, cell_size, grid_type, mode)

    buf = io.BytesIO()
    page_w, page_h = A4
    c = pdf_canvas.Canvas(buf, pagesize=A4)

    # 将图片适配到A4页面
    img_w, img_h = img.size
    scale = min(page_w / img_w, page_h / img_h) * 0.9
    draw_w, draw_h = img_w * scale, img_h * scale
    x = (page_w - draw_w) / 2
    y = (page_h - draw_h) / 2

    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")
    img_buf.seek(0)

    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(img_buf), x, y, draw_w, draw_h)
    c.save()
    buf.seek(0)

    return StreamingResponse(
        buf,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=copybook.pdf"},
    )


@app.get("/api/charinfo")
async def char_info(char: str = Query(..., min_length=1, max_length=1)):
    """查询单字在字库中的信息"""
    info = CHAR_DB.get(char, [])
    has_image = len(list(CHAR_DIR.glob(f"{char}_*.png"))) > 0
    return {
        "char": char,
        "has_image": has_image,
        "sources": info,
    }


@app.get("/api/stats")
async def stats():
    """字库统计"""
    image_count = len(list(CHAR_DIR.glob("*.png")))
    return {
        "total_chars_in_db": len(CHAR_DB),
        "total_images": image_count,
    }
