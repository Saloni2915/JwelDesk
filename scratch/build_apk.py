import os
import zipfile
import io
import hashlib
import struct
import base64
import datetime
import zlib
from PIL import Image

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
import apksigcopier

src_apk = r'c:\Users\Admin\JwelDesk\static\downloads\JewelDesk.apk'
output_apk = r'c:\Users\Admin\JwelDesk\static\downloads\JewelDesk.apk'
temp_output = r'c:\Users\Admin\JwelDesk\scratch\jeweldesk_rebuilt.apk'

icon_512_path = r'c:\Users\Admin\JwelDesk\static\icons\icon-512x512.png'
base_icon = Image.open(icon_512_path).convert('RGBA')

# Prepare icon mappings
icon_sizes = {
    'res/9w.png': (48, 48),
    'res/yn.png': (72, 72),
    'res/FS.png': (96, 96),
    'res/RJ.png': (144, 144),
    'res/o-.png': (192, 192),
    'res/zR.png': (48, 48),
    'res/8c.png': (72, 72),
    'res/wb.png': (96, 96),
    'res/fO.png': (144, 144),
    'res/Gc.png': (192, 192),
}

# Adaptive foreground icons (have transparent margin)
foreground_sizes = {
    'res/QZ.png': (108, 108),
    'res/zr.png': (162, 162),
    'res/Em.png': (216, 216),
    'res/Lf.png': (324, 324),
    'res/as.png': (432, 432),
}

icon_bytes_map = {}
for name, sz in icon_sizes.items():
    resized = base_icon.resize(sz, Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    resized.save(buf, format='PNG')
    icon_bytes_map[name] = buf.getvalue()

for name, sz in foreground_sizes.items():
    # Adaptive icon foreground is typically 72/108 of canvas, center it
    w, h = sz
    inner_w, inner_h = int(w * 0.72), int(h * 0.72)
    inner = base_icon.resize((inner_w, inner_h), Image.Resampling.LANCZOS)
    canvas = Image.new('RGBA', sz, (0, 0, 0, 0))
    offset_x = (w - inner_w) // 2
    offset_y = (h - inner_h) // 2
    canvas.paste(inner, (offset_x, offset_y), inner)
    buf = io.BytesIO()
    canvas.save(buf, format='PNG')
    icon_bytes_map[name] = buf.getvalue()

print(f"Generated {len(icon_bytes_map)} replacement launcher icons.")

zin = zipfile.ZipFile(src_apk, 'r')
buf = io.BytesIO()
zout = zipfile.ZipFile(buf, 'w', compression=zipfile.ZIP_DEFLATED)

manifest_lines = ['Manifest-Version: 1.0\r\nCreated-By: 1.0 (JewelDesk Android Package)\r\n\r\n']

for item in zin.infolist():
    if item.filename.startswith('META-INF/'):
        continue
    data = zin.read(item.filename)

    # 1. Update AndroidManifest.xml
    if item.filename == 'AndroidManifest.xml':
        old_pkg_utf16 = 'in.byajbatta.app'.encode('utf-16le')
        new_pkg_utf16 = 'in.jeweldesk.app'.encode('utf-16le')
        assert len(old_pkg_utf16) == len(new_pkg_utf16), "Package name length mismatch!"
        count = data.count(old_pkg_utf16)
        print(f"Replacing {count} occurrences of package in AndroidManifest.xml")
        data = data.replace(old_pkg_utf16, new_pkg_utf16)

    # 2. Update resources.arsc (App name in strings.xml table)
    elif item.filename == 'resources.arsc':
        old_name = b'Byaj Batta'
        new_name = b'Jewel Desk'
        assert len(old_name) == len(new_name), "App name length mismatch!"
        count = data.count(old_name)
        print(f"Replacing {count} occurrences of app name in resources.arsc")
        data = data.replace(old_name, new_name)

    # 3. Update classes.dex
    elif item.filename == 'classes.dex':
        old_dex = b'byajbatta'
        new_dex = b'jeweldesk'
        assert len(old_dex) == len(new_dex), "DEX string length mismatch!"
        count = data.count(old_dex)
        print(f"Replacing {count} occurrences of {old_dex} in classes.dex")
        data = data.replace(old_dex, new_dex)
        # Recalculate DEX SHA-1 signature (bytes 12-32)
        sha1 = hashlib.sha1(data[32:]).digest()
        data = data[:12] + sha1 + data[32:]
        # Recalculate DEX Adler32 checksum (bytes 8-12)
        adler = zlib.adler32(data[12:]) & 0xffffffff
        data = data[:8] + struct.pack('<I', adler) + data[12:]

    # 4. Update capacitor config
    elif item.filename == 'assets/capacitor.config.json':
        cfg = data.decode('utf-8')
        cfg = cfg.replace('https://byajbatta.in/start', 'https://jwel-desk.vercel.app')
        cfg = cfg.replace('in.byajbatta.app', 'in.jeweldesk.app')
        cfg = cfg.replace('com.jeweldesk.app', 'in.jeweldesk.app')
        cfg = cfg.replace('Byaj Batta', 'JewelDesk')
        data = cfg.encode('utf-8')

    # 5. Replace launcher icon drawables
    elif item.filename in icon_bytes_map:
        data = icon_bytes_map[item.filename]

    zout.writestr(item, data)
    digest = hashlib.sha256(data).digest()
    digest_b64 = base64.b64encode(digest).decode('ascii')
    manifest_lines.append(f'Name: {item.filename}\r\nSHA-256-Digest: {digest_b64}\r\n\r\n')

# Add v1 signature (META-INF)
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

# Generate consistent self-signed key & cert
key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.COMMON_NAME, 'JewelDesk'),
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'JewelDesk Software Technologies'),
    x509.NameAttribute(NameOID.COUNTRY_NAME, 'IN'),
])
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(12345678901234567890)
    .not_valid_before(datetime.datetime(2024, 1, 1, tzinfo=datetime.timezone.utc))
    .not_valid_after(datetime.datetime(2044, 1, 1, tzinfo=datetime.timezone.utc))
    .sign(key, hashes.SHA256())
)
builder = pkcs7.PKCS7SignatureBuilder().set_data(sf_data)
builder = builder.add_signer(cert, key, hashes.SHA256())
rsa_data = builder.sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
zout.writestr('META-INF/CERT.RSA', rsa_data)

zout.close()
zin.close()

# Save v1 APK
v1_bytes = buf.getvalue()
temp_v1 = r'c:\Users\Admin\JwelDesk\scratch\jeweldesk_v1_temp.apk'
with open(temp_v1, 'wb') as f:
    f.write(v1_bytes)

# Add v2 signature
cd_offset, eocd_offset, _ = apksigcopier.zip_data(temp_v1)
sb_offset = cd_offset
CHUNK_SIZE = 1048576

def compute_v2_digest():
    with open(temp_v1, 'rb') as f:
        chunk_digests = []
        for start, end in [(0, sb_offset), (cd_offset, eocd_offset), (eocd_offset, os.path.getsize(temp_v1))]:
            f.seek(start)
            rem = end - start
            while rem > 0:
                n = min(rem, CHUNK_SIZE)
                cdata = f.read(n)
                if not cdata:
                    break
                rem -= len(cdata)
                chunk_digests.append(hashlib.sha256(b'\xa5' + struct.pack('<I', len(cdata)) + cdata).digest())
        return hashlib.sha256(b'\x5a' + struct.pack('<I', len(chunk_digests)) + b''.join(chunk_digests)).digest()

v2_digest = compute_v2_digest()
from cryptography.hazmat.primitives.asymmetric import padding
sig = key.sign(v2_digest, padding.PKCS1v15(), hashes.SHA256())
cert_der = cert.public_bytes(serialization.Encoding.DER)

sig_entry = struct.pack('<I', 0x0103) + struct.pack('<I', len(sig)) + sig
signatures = struct.pack('<I', len(sig_entry)) + sig_entry

digest_entry = struct.pack('<I', 0x0103) + struct.pack('<I', len(v2_digest)) + v2_digest
digests = struct.pack('<I', len(digest_entry)) + digest_entry

certs = struct.pack('<I', len(cert_der)) + cert_der
certs_seq = struct.pack('<I', len(certs)) + certs

signed_data = (
    struct.pack('<I', len(digests)) + digests +
    struct.pack('<I', len(certs_seq)) + certs_seq +
    struct.pack('<I', 0)
)

signer = (
    struct.pack('<I', len(signed_data)) + signed_data +
    struct.pack('<I', len(signatures)) + signatures +
    struct.pack('<I', len(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo))) +
    key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
)

signers = struct.pack('<I', len(signer)) + signer
v2_block_value = struct.pack('<I', len(signers)) + signers
v2_pair = struct.pack('<I', 0x7109871a) + v2_block_value
id_value_pairs = struct.pack('<Q', len(v2_pair)) + v2_pair

sb_size = len(id_value_pairs) + 16 + 8
signing_block = (
    struct.pack('<Q', sb_size) +
    id_value_pairs +
    struct.pack('<Q', sb_size) +
    b'APK Sig Block 42'
)

with open(temp_v1, 'rb') as f:
    p1 = f.read(sb_offset)
    p2 = f.read()

# Update Central Directory offset in EOCD
eocd_pos = eocd_offset - sb_offset
new_cd_offset = cd_offset + len(signing_block)
p2_mod = p2[:eocd_pos + 16] + struct.pack('<I', new_cd_offset) + p2[eocd_pos + 20:]

with open(temp_output, 'wb') as f:
    f.write(p1 + signing_block + p2_mod)

print("V2 signed APK built successfully at:", temp_output)
