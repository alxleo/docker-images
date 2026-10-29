"""Exercise the native decoder boundary and conversion API in the rebuilt image."""

import io
import struct
from pathlib import Path
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
