import os
from PIL import Image, ImageFilter

BASE_DIR = r'C:\Users\Admin\JwelDesk'
SRC_APP_ICON = r'C:\Users\Admin\.gemini\antigravity-ide\brain\5a47d260-6cda-408a-baa2-da3880cc3b1c\.user_uploaded\media_1791541779300.jpg'
SRC_LOGO_TEXT = r'C:\Users\Admin\.gemini\antigravity-ide\brain\5a47d260-6cda-408a-baa2-da3880cc3b1c\.user_uploaded\media_1791541825971.jpg'

ICONS_DIR = os.path.join(BASE_DIR, 'static', 'icons')
BRANDING_DIR = os.path.join(BASE_DIR, 'static', 'images', 'branding')
MEDIA_COMPANY_DIR = os.path.join(BASE_DIR, 'media', 'company')
os.makedirs(ICONS_DIR, exist_ok=True)
os.makedirs(BRANDING_DIR, exist_ok=True)
os.makedirs(MEDIA_COMPANY_DIR, exist_ok=True)

# -------------------------------------------------------------
# 1. Master Squircle Icon Extraction with pristine anti-aliasing
# -------------------------------------------------------------
src_icon = Image.open(SRC_APP_ICON).convert('RGBA')
# Crop centered 720x720 around (508, 484)
cropped = src_icon.crop((148, 124, 868, 844))
cw, ch = cropped.size

from collections import deque
seeds = []
for x in range(cw):
    seeds.append((x, 0))
    seeds.append((x, ch - 1))
for y in range(ch):
    seeds.append((0, y))
    seeds.append((cw - 1, y))

visited = set()
q = deque()
for s in seeds:
    p = cropped.getpixel(s)
    if p[0] > 180 and p[1] > 160 and p[2] > 140:
        visited.add(s)
        q.append(s)

cream_mask = Image.new('L', (cw, ch), 0)
while q:
    x, y = q.popleft()
    p = cropped.getpixel((x, y))
    r, g, b = p[:3]
    is_bg = (r > 175 and g > 155 and b > 140 and (r - b) < 42) or (r > 200 and g > 185 and (r - b) < 48)
    if is_bg:
        cream_mask.putpixel((x, y), 255)
        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < cw and 0 <= ny < ch and (nx, ny) not in visited:
                visited.add((nx, ny))
                q.append((nx, ny))

dilated_cream = cream_mask.filter(ImageFilter.MaxFilter(3))
smooth_cream = dilated_cream.filter(ImageFilter.GaussianBlur(0.8))

squircle = cropped.copy()
alpha = Image.new('L', (cw, ch), 0)
for y in range(ch):
    for x in range(cw):
        if x < 4 or x > 705 or y < 16 or y > 710:
            alpha.putpixel((x, y), 0)
        else:
            val = 255 - smooth_cream.getpixel((x, y))
            alpha.putpixel((x, y), val)

squircle.putalpha(alpha)

# Clean residual shadow fringes
pix = squircle.load()
for y in range(ch):
    for x in range(cw):
        r, g, b, a = pix[x, y]
        if a < 70:
            pix[x, y] = (0, 0, 0, 0)
        elif y > 680 and (r < 120 or g < 90):
            pix[x, y] = (0, 0, 0, 0)
        elif (x < 12 or x > 696) and a < 140:
            pix[x, y] = (0, 0, 0, 0)

bbox = squircle.getbbox()
master_squircle = squircle.crop(bbox)
ms_w, ms_h = master_squircle.size
print(f"Master squircle cleaned: {ms_w}x{ms_h}")

# -------------------------------------------------------------
# 2. Standard PWA & Mobile Icon Generation
# -------------------------------------------------------------
def create_standard_icon(canvas_size, padding_ratio=0.94):
    canvas = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    target_dim = int(canvas_size * padding_ratio)
    scale = target_dim / max(ms_w, ms_h)
    new_w = max(1, int(ms_w * scale))
    new_h = max(1, int(ms_h * scale))
    resized = master_squircle.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = (canvas_size - new_w) // 2
    y = (canvas_size - new_h) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas

def create_maskable_icon(canvas_size):
    # W3C PWA Maskable specification: full-bleed background, safe zone circle = 80% diameter
    bg = Image.new('RGBA', (canvas_size, canvas_size), (20, 15, 9, 255)) # Luxury Roast Chocolate
    # Target emblem size: 76% of canvas
    target_dim = int(canvas_size * 0.76)
    scale = target_dim / max(ms_w, ms_h)
    new_w = max(1, int(ms_w * scale))
    new_h = max(1, int(ms_h * scale))
    resized = master_squircle.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = (canvas_size - new_w) // 2
    y = (canvas_size - new_h) // 2
    bg.paste(resized, (x, y), resized)
    return bg

# Master 1024x1024
app_icon_1024 = create_standard_icon(1024, 0.94)
app_icon_1024.save(os.path.join(BRANDING_DIR, 'app_icon.png'), format='PNG', optimize=True)
app_icon_1024.save(os.path.join(BRANDING_DIR, 'app_icon_transparent_corners.png'), format='PNG', optimize=True)
print("Saved 1024x1024 app_icon.png and app_icon_transparent_corners.png")

# PWA icons
icon_512 = create_standard_icon(512, 0.94)
icon_512.save(os.path.join(ICONS_DIR, 'icon-512x512.png'), format='PNG', optimize=True)

icon_192 = create_standard_icon(192, 0.94)
icon_192.save(os.path.join(ICONS_DIR, 'icon-192x192.png'), format='PNG', optimize=True)

apple_touch = create_standard_icon(180, 0.94)
apple_touch.save(os.path.join(ICONS_DIR, 'apple-touch-icon.png'), format='PNG', optimize=True)

fav_32 = create_standard_icon(32, 0.96)
fav_32.save(os.path.join(ICONS_DIR, 'favicon-32x32.png'), format='PNG', optimize=True)

fav_16 = create_standard_icon(16, 0.96)
fav_16.save(os.path.join(ICONS_DIR, 'favicon-16x16.png'), format='PNG', optimize=True)

fav_48 = create_standard_icon(48, 0.96)
fav_32.save(os.path.join(ICONS_DIR, 'favicon.ico'), format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
print("Saved standard PWA icons and favicon.ico")

# Maskable icons
maskable_512 = create_maskable_icon(512)
maskable_512.save(os.path.join(ICONS_DIR, 'icon-maskable-512x512.png'), format='PNG', optimize=True)

maskable_192 = create_maskable_icon(192)
maskable_192.save(os.path.join(ICONS_DIR, 'icon-maskable-192x192.png'), format='PNG', optimize=True)
print("Saved maskable icons (512x512, 192x192)")

# -------------------------------------------------------------
# 3. Horizontal Company Logo Generation (1024 x 254)
# -------------------------------------------------------------
src_wm = Image.open(SRC_LOGO_TEXT).convert('RGBA')
wm_raw = src_wm.crop((154, 664, 868, 735))

wm_rgba = wm_raw.copy()
pix_wm = wm_rgba.load()
for y in range(wm_raw.height):
    for x in range(wm_raw.width):
        r, g, b, a = pix_wm[x, y]
        if r > 210 and g > 200 and b > 185 and (r - b) < 35:
            pix_wm[x, y] = (0, 0, 0, 0)
        elif r > 180 and g > 175 and b > 165 and (r - b) < 25:
            pix_wm[x, y] = (0, 0, 0, 0)

logo_canvas = Image.new('RGBA', (1024, 254), (0, 0, 0, 0))

sq_h = 214
sq_w = int(ms_w * (sq_h / ms_h))
sq_resized = master_squircle.resize((sq_w, sq_h), Image.Resampling.LANCZOS)
logo_canvas.paste(sq_resized, (32, (254 - sq_h) // 2), sq_resized)

wm_w = 680
wm_h = int(wm_raw.height * (wm_w / wm_raw.width))
wm_resized = wm_rgba.resize((wm_w, wm_h), Image.Resampling.LANCZOS)
logo_canvas.paste(wm_resized, (32 + sq_w + 32, (254 - wm_h) // 2), wm_resized)

logo_path = os.path.join(BRANDING_DIR, 'logo.png')
logo_canvas.save(logo_path, format='PNG', optimize=True)

# Also save copy in media/company/logo.png
media_logo_path = os.path.join(MEDIA_COMPANY_DIR, 'logo.png')
logo_canvas.save(media_logo_path, format='PNG', optimize=True)
print(f"Saved horizontal brand logo to {logo_path} and {media_logo_path}")

print("\nALL PRODUCTION ASSETS CREATED SUCCESSFULLY!")
