import urllib.request
import urllib.parse
import re
from http.cookiejar import CookieJar

cj = CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

get_url = 'https://jwel-desk.vercel.app/accounts/password-reset/'
req = urllib.request.Request(get_url, headers={'User-Agent': 'Mozilla/5.0'})
resp = opener.open(req)
html = resp.read().decode('utf-8')

csrf_match = re.search(r'name=["\']csrfmiddlewaretoken["\'] value=["\']([^"\']+)["\']', html)
csrf_token = csrf_match.group(1) if csrf_match else None
if not csrf_token:
    for c in cj:
        if c.name == 'csrftoken':
            csrf_token = c.value
            break

print('CSRF token obtained:', csrf_token[:10] if csrf_token else 'None')

post_data = urllib.parse.urlencode({
    'csrfmiddlewaretoken': csrf_token,
    'email': 'salonisoni15dec2002@gmail.com'
}).encode('utf-8')

post_req = urllib.request.Request(
    get_url,
    data=post_data,
    headers={
        'User-Agent': 'Mozilla/5.0',
        'Referer': get_url,
    }
)
try:
    post_resp = opener.open(post_req)
    print('POST response URL:', post_resp.geturl())
    print('POST response code:', post_resp.status)
except urllib.error.HTTPError as e:
    print('POST HTTP Error:', e.code, e.read().decode())
except Exception as e:
    print('POST Error:', e)
