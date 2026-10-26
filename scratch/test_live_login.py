import urllib.request
import urllib.parse
import http.cookiejar
import re
import sys

user_identifier = sys.argv[1] if len(sys.argv) > 1 else 'salonisoni15dec2002@gmail.com'
user_password = sys.argv[2] if len(sys.argv) > 2 else 'Saloni@11111'

cj = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

res = opener.open('https://jwel-desk.vercel.app/accounts/login/')
html = res.read().decode('utf-8')
m = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', html)
token = m.group(1) if m else ''

post_data = urllib.parse.urlencode({
    'username': user_identifier,
    'password': user_password,
    'csrfmiddlewaretoken': token
}).encode('utf-8')

req = urllib.request.Request(
    'https://jwel-desk.vercel.app/accounts/login/',
    data=post_data,
    headers={
        'Referer': 'https://jwel-desk.vercel.app/accounts/login/',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
    }
)

login_res = opener.open(req)
final_url = login_res.geturl()
cookies = [c.name for c in cj]
print(f"Testing login for: {user_identifier}")
print("Final URL:", final_url)
print("Cookies:", cookies)
if 'sessionid' in cookies and '/login/' not in final_url:
    print(">>> SUCCESS: Login worked! <<<")
else:
    print(">>> FAILED: Login failed! <<<")
    # Check if there is an error message on the page
    resp_body = login_res.read().decode('utf-8')
    err_m = re.search(r'Sign In Failed|Invalid username or password|[\w\s.]+alert--error', resp_body)
    if err_m:
        print("Error on page snippet:", err_m.group(0))
