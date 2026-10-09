import os
import shutil
from PIL import Image
import django

BASE_DIR = r'C:\Users\Admin\JwelDesk'
SRC_LOGO_PHOTO = r'C:\Users\Admin\.gemini\antigravity-ide\brain\5a47d260-6cda-408a-baa2-da3880cc3b1c\.tempmediaStorage\media_1791543847004.jpg'

BRANDING_DIR = os.path.join(BASE_DIR, 'static', 'images', 'branding')
MEDIA_COMPANY_DIR = os.path.join(BASE_DIR, 'media', 'company')
os.makedirs(BRANDING_DIR, exist_ok=True)
os.makedirs(MEDIA_COMPANY_DIR, exist_ok=True)

# 1. Load source image
src = Image.open(SRC_LOGO_PHOTO).convert('RGBA')

# 2. Tight crop of the stacked company logo (JD monogram + — JEWELDESK —)
# Bounding box is roughly (154, 220, 868, 740)
crop_stacked = src.crop((140, 205, 882, 750))
stacked_path = os.path.join(BRANDING_DIR, 'company_logo.png')
crop_stacked.save(stacked_path, format='PNG', optimize=True)

# Also save directly to media/company/logo.png
media_logo_path = os.path.join(MEDIA_COMPANY_DIR, 'logo.png')
crop_stacked.save(media_logo_path, format='PNG', optimize=True)
print(f"Saved stacked company logo to {stacked_path} and {media_logo_path}")

# 3. Horizontal brand logo (1024 x 254) for headers & navigation
# Monogram crop:
mono_raw = src.crop((230, 205, 845, 635))
w, h = mono_raw.size
mono_rgba = mono_raw.copy()
pix = mono_rgba.load()
for y in range(h):
    for x in range(w):
        r, g, b, a = pix[x, y]
        if r > 215 and g > 205 and b > 195 and (r - b) < 30:
            pix[x, y] = (0, 0, 0, 0)
        elif r > 190 and g > 180 and b > 170 and (r - b) < 22:
            pix[x, y] = (0, 0, 0, 0)

mono_bbox = mono_rgba.getbbox()
mono_tight = mono_rgba.crop(mono_bbox)

# Wordmark crop:
wm_raw = src.crop((154, 664, 868, 735))
wm_rgba = wm_raw.copy()
pix_wm = wm_rgba.load()
for y in range(wm_raw.height):
    for x in range(wm_raw.width):
        r, g, b, a = pix_wm[x, y]
        if r > 210 and g > 200 and b > 185 and (r - b) < 35:
            pix_wm[x, y] = (0, 0, 0, 0)
        elif r > 180 and g > 175 and b > 165 and (r - b) < 25:
            pix_wm[x, y] = (0, 0, 0, 0)

wm_bbox = wm_rgba.getbbox()
wm_tight = wm_rgba.crop(wm_bbox)

# Compose horizontal logo
horizontal_canvas = Image.new('RGBA', (1024, 254), (0, 0, 0, 0))
m_h = 220
m_w = int(mono_tight.width * (m_h / mono_tight.height))
m_resized = mono_tight.resize((m_w, m_h), Image.Resampling.LANCZOS)
horizontal_canvas.paste(m_resized, (36, (254 - m_h) // 2), m_resized)

wm_w = 650
wm_h = int(wm_tight.height * (wm_w / wm_tight.width))
wm_resized = wm_tight.resize((wm_w, wm_h), Image.Resampling.LANCZOS)
horizontal_canvas.paste(wm_resized, (36 + m_w + 24, (254 - wm_h) // 2), wm_resized)

header_logo_path = os.path.join(BRANDING_DIR, 'logo.png')
horizontal_canvas.save(header_logo_path, format='PNG', optimize=True)
print(f"Saved horizontal brand logo to {header_logo_path}")

# 4. Update Django CompanySettings in database
import sys
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from accounts.models import CompanySettings
from django.core.cache import cache

company = CompanySettings.load()
company.logo = 'company/logo.png'
company.save()
cache.delete('company_settings:singleton')
print(f"Updated CompanySettings (pk={company.pk}) logo to 'company/logo.png'!")

print("\nALL COMPANY LOGO ASSETS UPDATED SUCCESSFULLY!")
