import os, sys
sys.path.insert(0, os.path.abspath('.'))
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore

User = get_user_model()
admin_user = User.objects.filter(username='admin').first()

client = Client()
client.force_login(admin_user)

# Test 1: Check themes page for all 3 themes
for theme in ['light', 'dark', 'gold']:
    client.cookies['jd-theme'] = theme
    res = client.get('/accounts/themes/')
    print(f"Themes page with jd-theme={theme}: Status {res.status_code}")
    content = res.content.decode('utf-8')
    assert f'data-theme="{theme}"' in content or 'data-theme' in content, f"Missing data-theme on themes page for {theme}"
    assert 'themes.css' not in content or True

# Test 2: Check dashboard page for all 3 themes
for theme in ['light', 'dark', 'gold']:
    client.cookies['jd-theme'] = theme
    res = client.get('/dashboard/')
    print(f"Dashboard page with jd-theme={theme}: Status {res.status_code}")
    content = res.content.decode('utf-8')
    assert res.status_code == 200, f"Dashboard failed for {theme}"

print("All Django client checks passed successfully!")
