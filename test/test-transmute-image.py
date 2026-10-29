"""Exercise the native decoder boundary and conversion API in the rebuilt image."""

import io
import struct
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from converters.pillow_convert import PillowConverter
from fastapi.testclient import TestClient
from main import create_app
from PIL import Image


def segment(marker, payload):
    return bytes([255, marker]) + struct.pack(">H", len(payload) + 2) + payload


# Standards-compliant uniform-gray lossless JPEG. The old decoder corrupts its
# heap when the native BLP converter requests a scaled thumbnail of this image.
width, height = 2400, 2200
counts = [0] * 16
counts[4] = 17
raw = (
    b"\xff\xd8"
    + segment(196, bytes([0]) + bytes(counts) + bytes(range(17)))
    + segment(195, struct.pack(">BHHB", 8, height, width, 1) + bytes([1, 17, 0]))
    + segment(218, bytes([1, 1, 0, 1, 0, 0]))
    + bytes((width * height * 5 + 7) // 8)
    + b"\xff\xd9"
)
source = Path("/tmp/lossless.jpg")
source.write_bytes(raw)
output = Path("/tmp/decoder-output")
output.mkdir()
try:
    PillowConverter(str(source), str(output), "jpeg", "blp").convert()
except RuntimeError as exc:
    assert isinstance(exc.__context__, OSError), exc
print("Lossless JPEG thumbnail decoder returned without memory corruption")


def convert(client, headers, name, contents, target):
    response = client.post("/api/files", headers=headers, files={"file": (name, contents)})
    assert response.status_code == 200, response.text
    file_id = response.json()["metadata"]["id"]
    response = client.post(
        "/api/conversions", headers=headers, json={"id": file_id, "output_format": target}
    )
    assert response.status_code == 200, response.text
    converted_id = response.json()["id"]
    response = client.get(f"/api/files/{converted_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.content


with TestClient(create_app()) as client:
    assert client.get("/api/health/ready").status_code == 200
    password = "synthetic-image-test-password"
    response = client.post("/api/users", json={"username": "fixture", "password": password})
    assert response.status_code == 201, response.text
    response = client.post("/api/users/token", data={"username": "fixture", "password": password})
    assert response.status_code == 200, response.text
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    for extension, image_format in (("png", "PNG"), ("heic", "HEIF")):
        contents = io.BytesIO()
        Image.new("RGB", (96, 64), "white").save(contents, format=image_format)
        jpeg = convert(client, headers, "fixture." + extension, contents.getvalue(), "jpeg")
        with Image.open(io.BytesIO(jpeg)) as result:
            result.load()
            assert result.format == "JPEG" and result.size == (96, 64)
        print(extension + " upload -> native JPEG download passed")

    docx = io.BytesIO()
    with ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Synthetic conversion acceptance</w:t></w:r></w:p></w:body></w:document>')
    pdf = convert(client, headers, "fixture.docx", docx.getvalue(), "pdf")
    assert pdf.startswith(b"%PDF-"), pdf[:40]
    print("DOCX upload -> native PDF download passed")

    # Generate a synthetic KF8 input with calibre's native writer, then exercise
    # the shipped AZW3 -> EPUB API and bundled KindleUnpack CLI.
    book = io.BytesIO()
    with ZipFile(book, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr("META-INF/container.xml", '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>')
        archive.writestr("content.opf", '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="id"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Synthetic KF8 acceptance</dc:title><dc:language>en</dc:language><dc:identifier id="id">urn:uuid:31a65b46-c026-4ee2-a476-90500c765735</dc:identifier></metadata><manifest><item id="chapter" href="chapter.xhtml" media-type="application/xhtml+xml"/></manifest><spine><itemref idref="chapter"/></spine></package>')
        archive.writestr("chapter.xhtml", '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Acceptance</title></head><body><p>Synthetic KF8 body survives extraction.</p></body></html>')
    with TemporaryDirectory() as temp:
        original = Path(temp) / "fixture.epub"
        original.write_bytes(book.getvalue())
        azw3 = Path(temp) / "fixture.azw3"
        subprocess.run(["/usr/bin/ebook-convert", str(original), str(azw3)], check=True, capture_output=True, timeout=30)
        epub = convert(client, headers, "reader's book.azw3", azw3.read_bytes(), "epub")
    with ZipFile(io.BytesIO(epub)) as archive:
        chapters = [archive.read(name) for name in archive.namelist() if name.endswith((".xhtml", ".html"))]
        assert any(b"Synthetic KF8 body survives extraction." in chapter for chapter in chapters)
    print("AZW3 upload -> bundled KindleUnpack -> EPUB download passed")
