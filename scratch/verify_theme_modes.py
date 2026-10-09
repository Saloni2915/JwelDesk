import os
import sys
from pathlib import Path
import django

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()
admin = User.objects.filter(is_superuser=True).first()

client = Client()
client.force_login(admin)

print("Checking 3 themes on themes page...")
for theme in ['light', 'dark', 'gold']:
    client.cookies['jd-theme'] = theme
    res = client.get(reverse('accounts:themes'))
    assert res.status_code == 200, f"Failed for theme {theme}"
    html = res.content.decode()
    assert f'data-theme-card="{theme}"' in html
    assert f'<div class="theme-card is-selected" data-theme-card="{theme}">' in html, f"Selected card missing for {theme}"
    print(f"  [OK] Theme '{theme}' correctly marks selected card when cookie is '{theme}'")

# Check atelier suite CSS is linked with cachebuster
assert 'atelier_suite.css' in html, "atelier_suite.css missing"
print("  [OK] atelier_suite.css is present in head")

# Check Google Fonts Cinzel is present
assert 'Cinzel' in html, "Cinzel font missing"
print("  [OK] Cinzel font is loaded in head")

print("\nALL THEME CHECKS PASSED!")
