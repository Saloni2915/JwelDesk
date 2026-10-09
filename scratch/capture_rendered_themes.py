import os, sys, time, subprocess
sys.path.insert(0, os.path.abspath('.'))
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.conf import settings

User = get_user_model()
admin_user = User.objects.filter(username='admin').first()

# Create active session for admin
session = SessionStore()
session['_auth_user_id'] = str(admin_user.pk)
session['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
session['_auth_user_hash'] = admin_user.get_session_auth_hash()
session.save()
session_key = session.session_key
print(f"Created admin session: {session_key}")

edge_path = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
artifact_dir = r"C:\Users\Admin\.gemini\antigravity-ide\brain\5a47d260-6cda-408a-baa2-da3880cc3b1c"

# We'll create a helper HTML that sets cookies and redirects, so Edge loads the page with authenticated session & theme!
targets = [
    ("dashboard", "/dashboard/", "light"),
    ("dashboard", "/dashboard/", "dark"),
    ("dashboard", "/dashboard/", "gold"),
    ("themes", "/accounts/themes/", "light"),
    ("themes", "/accounts/themes/", "dark"),
    ("themes", "/accounts/themes/", "gold"),
]

for name, path, theme in targets:
    helper_file = os.path.abspath(f"scratch/redir_{name}_{theme}.html")
    with open(helper_file, "w") as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <script>
        document.cookie = "sessionid={session_key}; path=/; max-age=86400";
        document.cookie = "jd-theme={theme}; path=/; max-age=86400";
        localStorage.setItem("jd-theme", "{theme}");
        window.location.replace("http://127.0.0.1:8000{path}");
    </script>
</head>
<body>Redirecting...</body>
</html>""")
    
    out_png = os.path.join(artifact_dir, f"{name}_{theme}.png")
    # Run Edge to screenshot
    cmd = [
        edge_path,
        "--headless=new",
        "--disable-gpu",
        f"--screenshot={out_png}",
        "--window-size=1280,900",
        f"file:///{helper_file.replace(os.sep, '/')}"
    ]
    # Edge needs 1-2 seconds to follow the JS redirect and render
    # Instead of file redirect, let's test if Edge captures after redirect or if we can use a small delay
    subprocess.run(cmd, capture_output=True, timeout=15)
    print(f"Captured {name}_{theme}.png -> Exists: {os.path.exists(out_png)}")

print("Capture complete!")
