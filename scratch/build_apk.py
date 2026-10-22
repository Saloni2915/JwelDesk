import os
import io
import zipfile
import hashlib
import struct
import base64
import datetime
from PIL import Image

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives.serialization import pkcs7
from cryptography.x509.oid import NameOID
import apksigtool

src_apk = r'c:\Users\Admin\JwelDesk\scratch\JewelDesk_backup.apk'
output_apk = r'c:\Users\Admin\JwelDesk\static\downloads\JewelDesk.apk'
temp_v1 = r'c:\Users\Admin\JwelDesk\scratch\jeweldesk_v1_aligned.apk'
key_path = r'c:\Users\Admin\JwelDesk\scratch\jeweldesk_key.pem'
cert_path = r'c:\Users\Admin\JwelDesk\scratch\jeweldesk_cert.pem'

# 1. Load or generate persistent signing key and certificate
if os.path.exists(key_path) and os.path.exists(cert_path):
    print("Loading existing signing key and certificate...")
    with open(key_path, 'rb') as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    with open(cert_path, 'rb') as f:
        cert = x509.load_pem_x509_certificate(f.read())
else:
    print("Generating persistent 2048-bit RSA release key and certificate...")
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
        .not_valid_after(datetime.datetime(2050, 1, 1, tzinfo=datetime.timezone.utc))
        .sign(key, hashes.SHA256())
    )
    with open(key_path, 'wb') as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    with open(cert_path, 'wb') as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    print(f"Saved persistent key to {key_path} and cert to {cert_path}")

cert_der = cert.public_bytes(serialization.Encoding.DER)
pubkey_der = key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)

# 2. Prepare brand launcher icons
icon_512_path = r'c:\Users\Admin\JwelDesk\static\icons\icon-512x512.png'
base_icon = Image.open(icon_512_path).convert('RGBA')

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

# 3. Read source APK and build aligned V1 zip
zin = zipfile.ZipFile(src_apk, 'r')
buf = io.BytesIO()
zout = zipfile.ZipFile(buf, 'w')

manifest_lines = ['Manifest-Version: 1.0\r\nCreated-By: 1.0 (JewelDesk Android Package)\r\n\r\n']

excluded_entries = {
    'assets/public/byajbatta-customer.apk',
    'assets/public/byajbatta.apk',
}

def write_aligned_entry(zfile, stream_buf, item_info, data_bytes, compress=True):
    zinfo = zipfile.ZipInfo(item_info.filename if isinstance(item_info, zipfile.ZipInfo) else item_info)
    zinfo.date_time = (2024, 1, 1, 0, 0, 0)
    zinfo.external_attr = 0o644 << 16
    
    if compress:
        zinfo.compress_type = zipfile.ZIP_DEFLATED
        zinfo.extra = b''
    else:
        zinfo.compress_type = zipfile.ZIP_STORED
        cur_pos = stream_buf.tell()
        name_bytes = zinfo.filename.encode('utf-8')
        # Local file header size: 30 + len(filename) + len(extra)
        # Data start offset: cur_pos + 30 + len(name_bytes) + len(extra)
        base_off = cur_pos + 30 + len(name_bytes)
        pad = (4 - (base_off % 4)) % 4
        zinfo.extra = b'\x00' * pad
    
    zfile.writestr(zinfo, data_bytes)

for item in zin.infolist():
    if item.filename.startswith('META-INF/'):
        continue
    if item.filename in excluded_entries:
        print(f"Excluding nested bloat file: {item.filename}")
        continue
    
    data = zin.read(item.filename)

    # A. Update AndroidManifest.xml
    if item.filename == 'AndroidManifest.xml':
        # Replace package name if needed
        old_pkg_utf16 = 'in.byajbatta.app'.encode('utf-16le')
        new_pkg_utf16 = 'in.jeweldesk.app'.encode('utf-16le')
        if old_pkg_utf16 in data:
            data = data.replace(old_pkg_utf16, new_pkg_utf16)
        
        # Modify binary AXML for stable SDK and version
        manifest_data = bytearray(data)
        # 1. compileSdkVersionCodename: replace '16' (utf-16le) with '14'
        if b'1\x006\x00' in manifest_data:
            idx = manifest_data.find(b'1\x006\x00')
            manifest_data[idx:idx+4] = b'1\x004\x00'
        # 2. compileSdkVersion: replace 36 at 0xd88 with 34
        if struct.unpack('<I', manifest_data[0xd88:0xd88+4])[0] == 36:
            manifest_data[0xd88:0xd88+4] = struct.pack('<I', 34)
        # 3. platformBuildVersionCode: replace 36 at 0xdc4 with 34
        if struct.unpack('<I', manifest_data[0xdc4:0xdc4+4])[0] == 36:
            manifest_data[0xdc4:0xdc4+4] = struct.pack('<I', 34)
        # 4. targetSdkVersion: replace 36 at 0xe24 with 34
        if struct.unpack('<I', manifest_data[0xe24:0xe24+4])[0] == 36:
            manifest_data[0xe24:0xe24+4] = struct.pack('<I', 34)
        # 5. versionCode: update 4 at 0xd60 to 5
        if struct.unpack('<I', manifest_data[0xd60:0xd60+4])[0] == 4:
            manifest_data[0xd60:0xd60+4] = struct.pack('<I', 5)
        data = bytes(manifest_data)
        print("Updated AndroidManifest.xml: targetSdkVersion=34, compileSdkVersion=34, versionCode=5")

    # B. Update resources.arsc
    elif item.filename == 'resources.arsc':
        if b'in.byajbatta.app' in data:
            data = data.replace(b'in.byajbatta.app', b'in.jeweldesk.app')
        if b'Byaj Batta' in data:
            data = data.replace(b'Byaj Batta', b'Jewel Desk')

    # C. Update classes.dex
    elif item.filename == 'classes.dex':
        if b'byajbatta' in data:
            data = data.replace(b'byajbatta', b'jeweldesk')
            sha1 = hashlib.sha1(data[32:]).digest()
            data = data[:12] + sha1 + data[32:]
            adler = zlib.adler32(data[12:]) & 0xffffffff
            data = data[:8] + struct.pack('<I', adler) + data[12:]

    # D. Update capacitor config
    elif item.filename == 'assets/capacitor.config.json':
        cfg = data.decode('utf-8')
        cfg = cfg.replace('https://byajbatta.in/start', 'https://jwel-desk.vercel.app')
        cfg = cfg.replace('in.byajbatta.app', 'in.jeweldesk.app')
        cfg = cfg.replace('com.jeweldesk.app', 'in.jeweldesk.app')
        cfg = cfg.replace('Byaj Batta', 'JewelDesk')
        data = cfg.encode('utf-8')

    # E. Replace launcher icon drawables
    elif item.filename in icon_bytes_map:
        data = icon_bytes_map[item.filename]

    # Preserve original compression method, but ensure stored files are 4-byte aligned
    should_compress = (item.compress_type != zipfile.ZIP_STORED)
    write_aligned_entry(zout, buf, item, data, compress=should_compress)

    digest = hashlib.sha256(data).digest()
    digest_b64 = base64.b64encode(digest).decode('ascii')
    manifest_lines.append(f'Name: {item.filename}\r\nSHA-256-Digest: {digest_b64}\r\n\r\n')

# 4. Generate V1 signature (META-INF)
manifest_data = ''.join(manifest_lines).encode('utf-8')
write_aligned_entry(zout, buf, 'META-INF/MANIFEST.MF', manifest_data, compress=False)

mf_digest = base64.b64encode(hashlib.sha256(manifest_data).digest()).decode('ascii')
sf_header = f'Signature-Version: 1.0\r\nCreated-By: 1.0 (JewelDesk Android Package)\r\nSHA-256-Digest-Manifest: {mf_digest}\r\n\r\n'
sf_entries = []
for line in manifest_lines[1:]:
    entry_hash = base64.b64encode(hashlib.sha256(line.encode('utf-8')).digest()).decode('ascii')
    name = line.split('\r\n')[0]
    sf_entries.append(f'{name}\r\nSHA-256-Digest: {entry_hash}\r\n\r\n')

sf_data = (sf_header + ''.join(sf_entries)).encode('utf-8')
write_aligned_entry(zout, buf, 'META-INF/CERT.SF', sf_data, compress=False)

builder = pkcs7.PKCS7SignatureBuilder().set_data(sf_data)
builder = builder.add_signer(cert, key, hashes.SHA256())
rsa_data = builder.sign(serialization.Encoding.DER, [pkcs7.PKCS7Options.DetachedSignature])
write_aligned_entry(zout, buf, 'META-INF/CERT.RSA', rsa_data, compress=False)

zout.close()
zin.close()

# Save v1 aligned APK
v1_bytes = buf.getvalue()
with open(temp_v1, 'wb') as f:
    f.write(v1_bytes)
print(f"Aligned V1 APK saved: {temp_v1} ({len(v1_bytes)} bytes)")

# 5. Compute APK V2 digest over the chunks
cd_offset, eocd_offset, _ = apksigtool.zip_data(temp_v1)
sb_offset = cd_offset
v2_digest = apksigtool.apk_digest_chunked(temp_v1, sb_offset, hashlib.sha256)
print(f"V2 Chunked SHA256 digest: {v2_digest.hex()}")

# 6. Build APK Signature Scheme V2 block
# A. Sequence of digests
digest_entry = struct.pack('<I', 0x0103) + struct.pack('<I', len(v2_digest)) + v2_digest
digest_entry_prefixed = struct.pack('<I', len(digest_entry)) + digest_entry
digests_seq = struct.pack('<I', len(digest_entry_prefixed)) + digest_entry_prefixed

# B. Sequence of certificates (CORRECTED: 2 prefixes, sequence length + cert entry length)
cert_entry_prefixed = struct.pack('<I', len(cert_der)) + cert_der
certs_seq = struct.pack('<I', len(cert_entry_prefixed)) + cert_entry_prefixed

# C. Sequence of additional attributes (empty)
attrs_seq = struct.pack('<I', 0)

# D. Signed data: length-prefixed sequence of digests, certs, attrs
signed_data = digests_seq + certs_seq + attrs_seq
signed_data_prefixed = struct.pack('<I', len(signed_data)) + signed_data

# E. RSA PKCS#1 v1.5 Signature over signed_data (CORRECTED: signs signed_data, NOT v2_digest!)
sig = key.sign(signed_data, padding.PKCS1v15(), hashes.SHA256())
sig_entry = struct.pack('<I', 0x0103) + struct.pack('<I', len(sig)) + sig
sig_entry_prefixed = struct.pack('<I', len(sig_entry)) + sig_entry
signatures_seq = struct.pack('<I', len(sig_entry_prefixed)) + sig_entry_prefixed

# F. Public key (SubjectPublicKeyInfo DER)
pubkey_prefixed = struct.pack('<I', len(pubkey_der)) + pubkey_der

# G. Signer
signer = signed_data_prefixed + signatures_seq + pubkey_prefixed
signer_prefixed = struct.pack('<I', len(signer)) + signer

# H. Signers sequence (v2_block_value)
signers_seq = struct.pack('<I', len(signer_prefixed)) + signer_prefixed

# I. ID-value pair for ID 0x7109871a (APK Signature Scheme v2)
v2_pair = struct.pack('<I', 0x7109871a) + signers_seq
id_value_pair = struct.pack('<Q', len(v2_pair)) + v2_pair

# J. APK Signing Block
sb_size = len(id_value_pair) + 16 + 8
signing_block = (
    struct.pack('<Q', sb_size) +
    id_value_pair +
    struct.pack('<Q', sb_size) +
    b'APK Sig Block 42'
)

# 7. Insert APK Signing Block before Central Directory and update EOCD
with open(temp_v1, 'rb') as f:
    p1 = f.read(sb_offset)
    p2 = f.read()

eocd_pos = eocd_offset - sb_offset
new_cd_offset = cd_offset + len(signing_block)
p2_mod = p2[:eocd_pos + 16] + struct.pack('<I', new_cd_offset) + p2[eocd_pos + 20:]

final_bytes = p1 + signing_block + p2_mod
with open(output_apk, 'wb') as f:
    f.write(final_bytes)
print(f"Final signed APK written to: {output_apk} ({len(final_bytes)} bytes)")

# 8. Thorough Verification
print("\n--- RUNNING VALIDATION CHECKS ---")

# Check 1: apksigtool V2 signature verification
sb_off_check, sig_block = apksigtool.extract_v2_sig(output_apk)
parsed_block = apksigtool.parse_apk_signing_block(sig_block, output_apk)
v2_verified = False
for pair in parsed_block.pairs:
    if pair.id == apksigtool.APK_SIGNATURE_SCHEME_V2_BLOCK_ID:
        v2_verified = pair.value.verified
        print(f"Check 1 (apksigtool V2 verification): {v2_verified}")
assert v2_verified is True, "FAIL: V2 signature verification failed!"

# Check 2: Androguard APK parsing & certificate extraction
from androguard.core.apk import APK
from loguru import logger
logger.disable('androguard')

apk = APK(output_apk)
print("Check 2a (is_signed_v1):", apk.is_signed_v1())
print("Check 2b (is_signed_v2):", apk.is_signed_v2())
assert apk.is_signed_v1() and apk.is_signed_v2(), "FAIL: APK is not both v1 and v2 signed!"

certs_v2 = apk.get_certificates_v2()
print(f"Check 2c (V2 certificates extracted): {len(certs_v2)}")
assert len(certs_v2) == 1, "FAIL: Could not parse V2 certificate!"
print(f"  Cert Subject: {certs_v2[0].subject.native}")

pkg = apk.get_package()
target_sdk = apk.get_target_sdk_version()
min_sdk = apk.get_min_sdk_version()
print(f"Check 2d (Package): {pkg}")
print(f"Check 2e (Min SDK): {min_sdk}")
print(f"Check 2f (Target SDK): {target_sdk}")
assert pkg == 'in.jeweldesk.app', f"FAIL: Unexpected package {pkg}"
assert target_sdk == '34', f"FAIL: Expected target SDK 34, got {target_sdk}"
assert min_sdk == '24', f"FAIL: Expected min SDK 24, got {min_sdk}"

# Check 3: 4-byte ZIP alignment of uncompressed files
def check_alignment(apk_path):
    misaligned = []
    with open(apk_path, 'rb') as f:
        data = f.read()
    eocd_idx = data.rfind(b'PK\x05\x06')
    cd_offset = struct.unpack('<I', data[eocd_idx+16:eocd_idx+20])[0]
    cd_records = struct.unpack('<H', data[eocd_idx+10:eocd_idx+12])[0]
    pos = cd_offset
    for _ in range(cd_records):
        comp_method = struct.unpack('<H', data[pos+10:pos+12])[0]
        fname_len = struct.unpack('<H', data[pos+28:pos+30])[0]
        extra_len = struct.unpack('<H', data[pos+30:pos+32])[0]
        comment_len = struct.unpack('<H', data[pos+32:pos+34])[0]
        local_hdr_off = struct.unpack('<I', data[pos+42:pos+46])[0]
        name = data[pos+46:pos+46+fname_len].decode('utf-8', 'replace')
        loc_fname_len = struct.unpack('<H', data[local_hdr_off+26:local_hdr_off+28])[0]
        loc_extra_len = struct.unpack('<H', data[local_hdr_off+28:local_hdr_off+30])[0]
        data_off = local_hdr_off + 30 + loc_fname_len + loc_extra_len
        if comp_method == 0:
            if data_off % 4 != 0:
                misaligned.append((name, data_off, data_off % 4))
        pos += 46 + fname_len + extra_len + comment_len
    return misaligned

misaligned = check_alignment(output_apk)
print(f"Check 3 (Zip alignment): {len(misaligned)} misaligned stored entries")
assert len(misaligned) == 0, f"FAIL: Misaligned entries found: {misaligned[:5]}"

print("\nALL VALIDATION CHECKS PASSED PERFECTLY!")
