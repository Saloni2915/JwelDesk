import os
from PIL import Image, ImageFilter, ImageDraw, ImageFont

SRC_PATH = r'C:\Users\Admin\.gemini\antigravity-ide\brain\5a47d260-6cda-408a-baa2-da3880cc3b1c\.user_uploaded\media_1791541779300.jpg'
BASE_DIR = r'C:\Users\Admin\JwelDesk'
ICONS_DIR = os.path.join(BASE_DIR, 'static', 'icons')
BRANDING_DIR = os.path.join(BASE_DIR, 'static', 'images', 'branding')
os.makedirs(ICONS_DIR, exist_ok=True)
os.makedirs(BRANDING_DIR, exist_ok=True)

# 1. Load source image
src = Image.open(SRC_PATH).convert('RGBA')
w, h = src.size

# 2. Extract squircle: Center at (508, 484), size 720x720
crop_box = (148, 124, 868, 844)
cropped = src.crop(crop_box)
cw, ch = cropped.size

# 3. Flood fill outer cream background from border seeds
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

# Clean fringe by dilating cream mask and soft feather
dilated_cream = cream_mask.filter(ImageFilter.MaxFilter(3))
smooth_cream = dilated_cream.filter(ImageFilter.GaussianBlur(0.8))

# Build squircle RGBA
squircle = cropped.copy()
alpha = Image.new('L', (cw, ch), 0)
for y in range(ch):
    for x in range(cw):
        # Clip strictly outside rim bounding box
        if x < 4 or x > 705 or y < 16 or y > 710:
            alpha.putpixel((x, y), 0)
        else:
            val = 255 - smooth_cream.getpixel((x, y))
            alpha.putpixel((x, y), val)

squircle.putalpha(alpha)

# Crop squircle to its exact alpha bbox
bbox = squircle.getbbox()
squircle_tight = squircle.crop(bbox) # approx 691 x 667
st_w, st_h = squircle_tight.size
print(f"Extracted master squircle size: {st_w}x{st_h}")

# Function to place squircle centered on transparent canvas
def make_centered_icon(canvas_size, icon_size=None):
    canvas = Image.new('RGBA', (canvas_size, canvas_size), (0, 0, 0, 0))
    if icon_size is None:
        icon_size = int(canvas_size * 0.94)
    # Maintain aspect ratio
    scale = icon_size / max(st_w, st_h)
    new_w = int(st_w * scale)
    new_h = int(st_h * scale)
    resized = squircle_tight.resize((new_w, new_h), Image.Resampling.LANCZOS)
    x = (canvas_size - new_w) // 2
    y = (canvas_size - new_h) // 2
    canvas.paste(resized, (x, y), resized)
    return canvas

# Function to create maskable icon (full-bleed dark background, emblem inside 80% safe zone circle)
def make_maskable_icon(canvas_size):
    # Full bleed background: dark luxury roast chocolate with subtle radial glow
    bg = Image.new('RGBA', (canvas_size, canvas_size), (20, 15, 9, 255)) # #140F09
    draw = ImageDraw.Draw(bg)
    
    # Safe zone for maskable icon is 80% diameter (safe circle = 0.8 * canvas_size)
    # Emblem size: 76% of canvas_size so it sits comfortably inside the 80% safe zone
    emblem_target = int(canvas_size * 0.76)
    scale = emblem_target / max(st_w, st_h)
    new_w = int(st_w * scale)
    new_h = int(st_h * scale)
    resized = squircle_tight.resize((new_w, new_h), Image.Resampling.LANCZOS)
    
    x = (canvas_size - new_w) // 2
    y = (canvas_size - new_h) // 2
    bg.paste(resized, (x, y), resized)
    return bg

# Generate Branding Master Files (1024x1024)
app_icon_1024 = make_centered_icon(1024, 960)
app_icon_1024.save(os.path.join(BRANDING_DIR, 'app_icon.png'), format='PNG', optimize=True)
app_icon_1024.save(os.path.join(BRANDING_DIR, 'app_icon_transparent_corners.png'), format='PNG', optimize=True)
print("Saved 1024x1024 app_icon.png & app_icon_transparent_corners.png")

# Generate Standard PWA Icons
icon_512 = make_centered_icon(512, 480)
icon_512.save(os.path.join(ICONS_DIR, 'icon-512x512.png'), format='PNG', optimize=True)

icon_192 = make_centered_icon(192, 180)
icon_192.save(os.path.join(ICONS_DIR, 'icon-192x192.png'), format='PNG', optimize=True)

apple_icon = make_centered_icon(180, 170)
apple_icon.save(os.path.join(ICONS_DIR, 'apple-touch-icon.png'), format='PNG', optimize=True)

fav_32 = make_centered_icon(32, 30)
fav_32.save(os.path.join(ICONS_DIR, 'favicon-32x32.png'), format='PNG', optimize=True)

fav_16 = make_centered_icon(16, 15)
fav_16.save(os.path.join(ICONS_DIR, 'favicon-16x16.png'), format='PNG', optimize=True)

fav_48 = make_centered_icon(48, 45)

# Save multi-res ICO
fav_32.save(os.path.join(ICONS_DIR, 'favicon.ico'), format='ICO', sizes=[(16, 16), (32, 32), (48, 48)])
print("Saved standard PWA icons and favicon.ico")

# Generate Maskable Icons
maskable_512 = make_maskable_icon(512)
maskable_512.save(os.path.join(ICONS_DIR, 'icon-maskable-512x512.png'), format='PNG', optimize=True)

maskable_192 = make_maskable_icon(192)
maskable_192.save(os.path.join(ICONS_DIR, 'icon-maskable-192x192.png'), format='PNG', optimize=True)
print("Saved maskable icons (512x512, 192x192)")

print("\nALL PWA ICONS GENERATED SUCCESSFULLY!")
