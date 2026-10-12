import os
import zipfile
import io
import hashlib
import struct
import base64
import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
import apksigcopier
from androguard.core.apk import APK

os.makedirs(r'c:\Users\Admin\JwelDesk\static\downloads', exist_ok=True)
src_apk = r'C:\Users\Admin\Downloads\byajbatta.apk'
dest_apk = r'c:\Users\Admin\JwelDesk\static\downloads\JewelDesk.apk'

print(f"Reading base APK from: {src_apk}")
icon_192 = None
icon_path = r'c:\Users\Admin\JwelDesk\static\icons\icon-192x192.png'
if os.path.exists(icon_path):
    with open(icon_path, 'rb') as f:
        icon_192 = f.read()

zin = zipfile.ZipFile(src_apk, 'r')
buf = io.BytesIO()
zout = zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED)

manifest_lines = ['Manifest-Version: 1.0\r\nCreated-By: 1.0 (JewelDesk Android Package)\r\n\r\n']

for item in zin.infolist():
    if item.filename.startswith('META-INF/'):
        continue
    data = zin.read(item.filename)
    if item.filename == 'assets/capacitor.config.json':
        cfg = data.decode('utf-8')
        cfg = cfg.replace('https://byajbatta.in/start', 'https://jwel-desk.vercel.app')
        cfg = cfg.replace('Byaj Batta', 'JewelDesk').replace('in.byajbatta.app', 'com.jeweldesk.app')
        data = cfg.encode('utf-8')
    elif icon_192 and item.filename in ('assets/public/icons/icon-192x192.png', 'assets/public/favicon.png', 'assets/public/apple-touch-icon.png'):
        data = icon_192
    
    zout.writestr(item, data)
    digest = hashlib.sha256(data).digest()
    digest_b64 = base64.b64encode(digest).decode('ascii')
    manifest_lines.append(f'Name: {item.filename}\r\nSHA-256-Digest: {digest_b64}\r\n\r\n')

# 3. Add v1 signature
manifest_data = ''.join(manifest_lines).encode('utf-8')
zout.writestr('META-INF/MANIFEST.MF', manifest_data)

mf_digest = base64.b64encode(hashlib.sha256(manifest_data).digest()).decode('ascii')
sf_header = f'Signature-Version: 1.0\r\nCreated-By: 1.0 (JewelDesk Android Package)\r\nSHA-256-Digest-Manifest: {mf_digest}\r\n\r\n'
sf_entries = []
for line in manifest_lines[1:]:
    entry_hash = base64.b64encode(hashlib.sha256(line.encode('utf-8')).digest()).decode('ascii')
    name = line.split('\r\n')[0]
    sf_entries.append(f'{name}\r\nSHA-256-Digest: {entry_hash}\r\n\r\n')

sf_data = (sf_header + ''.join(sf_entries)).encode('utf-8')
zout.writestr('META-INF/CERT.SF', sf_data)

# Generate key & cert
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, 'JewelDesk'),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'JewelDesk Software Technologies'),
])
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1))
    .not_valid_after(datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=10000))
    .sign(key, hashes.SHA256())
)
builder = pkcs7.PKCS7SignatureBuilder().set_data(sf_data)
builder = builder.add_signer(cert, key, hashes.SHA256())
rsa_data = builder.sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
zout.writestr('META-INF/CERT.RSA', rsa_data)

zout.close()
zin.close()

# 4. Save v1 apk bytes
v1_bytes = buf.getvalue()
temp_v1 = r'c:\Users\Admin\JwelDesk\scratch\jeweldesk_v1.apk'
with open(temp_v1, 'wb') as f:
    f.write(v1_bytes)

# 5. Add v2 signature
cd_offset, eocd_offset, _ = apksigcopier.zip_data(temp_v1)
sb_offset = cd_offset

CHUNK_SIZE = 1048576
digests = []

with open(temp_v1, 'rb') as fh:
    rem = sb_offset
    while rem > 0:
        chunk = fh.read(min(rem, CHUNK_SIZE))
        if not chunk: break
        rem -= len(chunk)
        digests.append(hashlib.sha256(b'\xa5' + len(chunk).to_bytes(4, 'little') + chunk).digest())

    fh.seek(cd_offset)
    rem = eocd_offset - cd_offset
    while rem > 0:
        chunk = fh.read(min(rem, CHUNK_SIZE))
        if not chunk: break
        rem -= len(chunk)
        digests.append(hashlib.sha256(b'\xa5' + len(chunk).to_bytes(4, 'little') + chunk).digest())

    fh.seek(eocd_offset)
    eocd = fh.read()
    eocd_patched = eocd[:16] + int.to_bytes(sb_offset, 4, 'little') + eocd[20:]
    for i in range(0, len(eocd_patched), CHUNK_SIZE):
        chunk = eocd_patched[i:i+CHUNK_SIZE]
        digests.append(hashlib.sha256(b'\xa5' + len(chunk).to_bytes(4, 'little') + chunk).digest())

root_digest = hashlib.sha256(b'\x5a' + len(digests).to_bytes(4, 'little') + b''.join(digests)).digest()

algo_id = 0x0103 # RSASSA-PKCS1-v1_5 SHA256
digest_entry = struct.pack('<LL', algo_id, len(root_digest)) + root_digest
digests_block = len(digest_entry).to_bytes(4, 'little') + digest_entry
digests_field = len(digests_block).to_bytes(4, 'little') + digests_block

cert_der = cert.public_bytes(serialization.Encoding.DER)
cert_entry = len(cert_der).to_bytes(4, 'little') + cert_der
certs_field = len(cert_entry).to_bytes(4, 'little') + cert_entry
attrs_field = (0).to_bytes(4, 'little')

signed_data = digests_field + certs_field + attrs_field
signed_data_field = len(signed_data).to_bytes(4, 'little') + signed_data

signature = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
sig_entry = struct.pack('<L', algo_id) + len(signature).to_bytes(4, 'little') + signature
sig_block = len(sig_entry).to_bytes(4, 'little') + sig_entry
sigs_field = len(sig_block).to_bytes(4, 'little') + sig_block

pubkey_der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
pubkey_field = len(pubkey_der).to_bytes(4, 'little') + pubkey_der

signer = signed_data_field + sigs_field + pubkey_field
signer_field = len(signer).to_bytes(4, 'little') + signer
v2_scheme_data = len(signer_field).to_bytes(4, 'little') + signer_field

pair_id = 0x7109871a
pair_data = struct.pack('<L', pair_id) + v2_scheme_data
pair_len = len(pair_data)
pair = struct.pack('<Q', pair_len) + pair_data

block_size = len(pair) + 24
signing_block = (
    struct.pack('<Q', block_size) +
    pair +
    struct.pack('<Q', block_size) +
    b'APK Sig Block 42'
)

part1 = v1_bytes[:cd_offset]
cd = v1_bytes[cd_offset:eocd_offset]
new_cd_offset = cd_offset + len(signing_block)
new_eocd = eocd[:16] + int.to_bytes(new_cd_offset, 4, 'little') + eocd[20:]

with open(dest_apk, 'wb') as f:
    f.write(part1 + signing_block + cd + new_eocd)

print(f"JewelDesk APK written successfully to: {dest_apk}")
print(f"File size: {os.path.getsize(dest_apk):,} bytes")

apk_obj = APK(dest_apk)
print(f"APK validation:")
print(f"  is_signed:    {apk_obj.is_signed()}")
print(f"  is_signed_v1: {apk_obj.is_signed_v1()}")
print(f"  is_signed_v2: {apk_obj.is_signed_v2()}")
