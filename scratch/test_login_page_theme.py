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
from django.urls import reverse

client = Client()

print("Testing login page rendering and theme...")
res = client.get(reverse('accounts:login'))
assert res.status_code == 200, f"Status code is {res.status_code}"
html = res.content.decode()

# 1. Must have data-theme="gold"
assert 'data-theme="gold"' in html, "HTML tag does not have data-theme='gold'"
print("  [OK] data-theme='gold' is present in HTML")

# 2. Must not have theme pills or theme switcher buttons
assert 'jd-theme-pills' not in html, "jd-theme-pills should not be present"
assert 'jd-theme-btn' not in html, "jd-theme-btn should not be present"
print("  [OK] Theme switcher buttons/pills are completely removed")

# 3. Must have trust badge
assert 'ISO 27001 Certified' in html, "Trust badge missing"
print("  [OK] ISO 27001 trust badge is present")

# 4. Must have golden luxury colors in inline styles
assert '#141009' in html, "Golden background #141009 missing"
assert '#221c10' in html, "Golden surface #221c10 missing"
print("  [OK] Luxury chocolate gold tokens are present in login page")

print("\nALL LOGIN PAGE CHECKS PASSED!")
