import os
import math
from PIL import Image, ImageDraw, ImageFilter

def generate_all_icons():
    print("=== Generating Flawless JewelDesk PWA & Branding Icons ===")
    
    # 1. Clean and isolate the central diamond emblem from static/images/branding/app_icon.png
    orig = Image.open('static/images/branding/app_icon.png').convert('RGBA')
    W_orig, H_orig = orig.size
    
    # Crop the inner square (80..944)
    inner_sq = orig.crop((80, 80, 944, 944)).convert('RGBA')
    W_in, H_in = inner_sq.size # 864, 864
    
    # Clean the four corners outside the diamond polygon so no old border fragments remain
    bg_solid = (22, 15, 9, 255) # Exact #160F09 brand color
    corner_mask = Image.new('L', (W_in, H_in), 255)
    cm_draw = ImageDraw.Draw(corner_mask)
    
    # Mask out corners
    cm_draw.polygon([(0, 0), (145, 0), (0, 145)], fill=0)
    cm_draw.polygon([(W_in, 0), (W_in - 145, 0), (W_in, 145)], fill=0)
    cm_draw.polygon([(0, H_in), (0, H_in - 245), (225, H_in)], fill=0)
    cm_draw.polygon([(W_in, H_in), (W_in, H_in - 245), (W_in - 225, H_in)], fill=0)
    
    corner_mask = corner_mask.filter(ImageFilter.GaussianBlur(6))
    
    clean_diamond = Image.new('RGBA', (W_in, H_in), bg_solid)
    clean_diamond.paste(inner_sq, (0, 0), corner_mask)
    
    # 2. Build 2048x2048 Master High-Precision Icon
    S = 2048
    margin = 84
    box = [margin, margin, S - margin, S - margin] # 84 to 1964 (1880x1880)
    radius = 410
    border_w = 26
    
    # Squircle mask for interior
    squircle_mask = Image.new('L', (S, S), 0)
    sm_draw = ImageDraw.Draw(squircle_mask)
    sm_draw.rounded_rectangle(box, radius=radius, fill=255)
    
    # Interior dark canvas
    interior = Image.new('RGBA', (S, S), bg_solid)
    
    # Resize clean diamond to fit with luxury breathing room (~76% width)
    target_diamond_s = 1530
    diamond_scaled = clean_diamond.resize((target_diamond_s, target_diamond_s), Image.Resampling.LANCZOS)
    
    # Position centered with optical balance
    pos_x = (S - target_diamond_s) // 2
    pos_y = (S - target_diamond_s) // 2 + 10
    interior.paste(diamond_scaled, (pos_x, pos_y))
    
    # Mask interior to squircle shape
    interior.putalpha(squircle_mask)
    
    # 3. Create Metallic Polished Gold Border
    gold_grad = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    g_draw = ImageDraw.Draw(gold_grad)
    for y in range(S):
        ratio = y / S
        # Luxury gold multi-stop metallic reflection
        if ratio < 0.25:
            t = ratio / 0.25
            r = int(255 * (1 - t) + 245 * t)
            g = int(240 * (1 - t) + 214 * t)
            b = int(185 * (1 - t) + 122 * t)
        elif ratio < 0.60:
            t = (ratio - 0.25) / 0.35
            r = int(245 * (1 - t) + 225 * t)
            g = int(214 * (1 - t) + 185 * t)
            b = int(122 * (1 - t) + 65 * t)
        elif ratio < 0.85:
            t = (ratio - 0.60) / 0.25
            r = int(225 * (1 - t) + 184 * t)
            g = int(185 * (1 - t) + 134 * t)
            b = int(65 * (1 - t) + 22 * t)
        else:
            t = (ratio - 0.85) / 0.15
            r = int(184 * (1 - t) + 150 * t)
            g = int(134 * (1 - t) + 100 * t)
            b = int(22 * (1 - t) + 12 * t)
        g_draw.line([(0, y), (S, y)], fill=(r, g, b, 255))
        
    # Border mask
    border_mask = Image.new('L', (S, S), 0)
    bm_draw = ImageDraw.Draw(border_mask)
    bm_draw.rounded_rectangle(box, radius=radius, fill=255)
    inner_box = [box[0] + border_w, box[1] + border_w, box[2] - border_w, box[3] - border_w]
    bm_draw.rounded_rectangle(inner_box, radius=radius - border_w, fill=0)
    
    # 3D inner bevel
    inner_bevel = Image.new('L', (S, S), 0)
    ib_draw = ImageDraw.Draw(inner_bevel)
    ib_draw.rounded_rectangle(inner_box, radius=radius - border_w, outline=255, width=4)
    
    gold_border = Image.new('RGBA', (S, S), (0, 0, 0, 0))
    gold_border.paste(gold_grad, (0, 0), border_mask)
    
    # Top-side light reflection on inner bevel
    bevel_color = Image.new('RGBA', (S, S), (255, 248, 220, 85))
    gold_border.paste(bevel_color, (0, 0), inner_bevel)
    
    # Composite: Interior + Gold Border
    master_2048 = Image.alpha_composite(interior, gold_border)
    
    # Downsample to 1024x1024 master
    master_1024 = master_2048.resize((1024, 1024), Image.Resampling.LANCZOS)
    
    # 4. Save Master Branding Icons
    master_1024.save('static/images/branding/app_icon.png', 'PNG')
    master_1024.save('static/images/branding/app_icon_transparent_corners.png', 'PNG')
    print("Saved app_icon.png & app_icon_transparent_corners.png (1024x1024)")
    
    # 5. Save Standard App Icons (Transparent Outside Squircle)
    icon_512 = master_1024.resize((512, 512), Image.Resampling.LANCZOS)
    icon_512.save('static/icons/icon-512x512.png', 'PNG')
    
    icon_192 = master_1024.resize((192, 192), Image.Resampling.LANCZOS)
    icon_192.save('static/icons/icon-192x192.png', 'PNG')
    
    apple_icon = master_1024.resize((180, 180), Image.Resampling.LANCZOS)
    apple_icon.save('static/icons/apple-touch-icon.png', 'PNG')
    
    favicon_32 = master_1024.resize((32, 32), Image.Resampling.LANCZOS)
    favicon_32.save('static/icons/favicon-32x32.png', 'PNG')
    
    favicon_16 = master_1024.resize((16, 16), Image.Resampling.LANCZOS)
    favicon_16.save('static/icons/favicon-16x16.png', 'PNG')
    
    # Multi-resolution favicon.ico
    master_1024.save('static/icons/favicon.ico', format='ICO', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    print("Saved standard PWA icons (512, 192, apple-touch, favicons)")
    
    # 6. Save Maskable Icons for Android PWA (Safe-Zone Compliant)
    # Full bleed background #160F09 with squircle badge safely centered within the 80% safe zone
    def make_maskable(size):
        canvas = Image.new('RGBA', (size, size), bg_solid)
        # 80% safe zone diameter is size * 0.8. We size the squircle badge to 80%
        badge_size = int(size * 0.80)
        badge = master_1024.resize((badge_size, badge_size), Image.Resampling.LANCZOS)
        offset = ((size - badge_size) // 2, (size - badge_size) // 2)
        canvas.paste(badge, offset, badge)
        return canvas
        
    maskable_512 = make_maskable(512)
    maskable_512.save('static/icons/icon-maskable-512x512.png', 'PNG')
    
    maskable_192 = make_maskable(192)
    maskable_192.save('static/icons/icon-maskable-192x192.png', 'PNG')
    print("Saved maskable icons (icon-maskable-512x512.png, icon-maskable-192x192.png)")
    
    print("=== All Icons Generated Flawlessly ===")

if __name__ == '__main__':
    generate_all_icons()
