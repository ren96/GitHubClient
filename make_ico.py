"""从 tubiao/logo.png 生成多尺寸 tubiao/tubiao.ico
用法：python make_ico.py
"""
from PIL import Image

SRC = "tubiao/logo.png"
DST = "tubiao/tubiao.ico"
SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def main():
    img = Image.open(SRC).convert("RGBA")
    max_side = max(img.size)
    if max_side < 256:
        # 原图太小，先放大到 256 再让 Pillow 从高分辨率往下降采样，避免糊
        scale = 256 / max_side
        img = img.resize(
            (int(img.width * scale), int(img.height * scale)),
            Image.LANCZOS,
        )
    img.save(DST, format="ICO", sizes=SIZES)
    print(f"已生成 {DST}，尺寸：{SIZES}")


if __name__ == "__main__":
    main()