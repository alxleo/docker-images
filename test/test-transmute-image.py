"""Exercise the native decoder boundary and conversion API in the rebuilt image."""

import io
import struct
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from api.routes import compression_jobs
from api.routes import jobs as conversion_jobs
from api.schemas import CompressionJobCreateRequest, ConversionJobCreateRequest
from background.cleanup import cleanup_once, job_cleanup_logic
from converters.pillow_convert import PillowConverter
from core import get_settings
from db import (
    CompressionDB,
    CompressionJobDB,
    CompressionRelationsDB,
    ConversionDB,
    ConversionJobDB,
    ConversionRelationsDB,
    FileDB,
    SettingsDB,
)
from fastapi import HTTPException
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


def convert(client, headers, name, contents, target, quality=None):
    response = client.post("/api/files", headers=headers, files={"file": (name, contents)})
    assert response.status_code == 200, response.text
    file_id = response.json()["metadata"]["id"]
    response = client.post(
        "/api/conversions", headers=headers,
        json={"id": file_id, "output_format": target, "quality": quality},
    )
    assert response.status_code == 200, response.text
    converted_id = response.json()["id"]
    response = client.get(f"/api/files/{converted_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.content


def retention_file(db, hours, contents=b"Synthetic retention acceptance", media_type="txt"):
    identifier = str(uuid.uuid4())
    extension = "." + media_type
    path = get_settings().output_dir / (identifier + extension)
    path.write_bytes(contents)
    metadata = {
        "id": identifier, "storage_path": str(path),
        "original_filename": "fixture" + extension, "media_type": media_type,
        "extension": extension, "size_bytes": path.stat().st_size,
        "sha256_checksum": "0" * 64, "user_id": "retention-fixture",
    }
    db.insert_file_metadata(metadata)
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time() - hours * 3600))
    with db.conn:
        db.conn.execute(f"UPDATE {db.TABLE_NAME} SET created_at = ? WHERE id = ?", (timestamp, identifier))
    return identifier, path


def check_retention():
    assert SettingsDB().get_settings("retention-fixture")["cleanup_ttl_minutes"] == 1440
    originals = FileDB()
    conversions = ConversionDB()
    compressions = CompressionDB()
    expired = [retention_file(db, 25) for db in (originals, conversions, compressions)]
    recent = [retention_file(db, 23) for db in (originals, conversions, compressions)]
    relation = {
        "original_file_id": expired[0][0], "original_filename": "fixture.txt",
        "original_media_type": "txt", "original_extension": ".txt",
        "original_size_bytes": 29, "user_id": "retention-fixture",
    }
    conversion_relations = ConversionRelationsDB()
    compression_relations = CompressionRelationsDB()
    conversion_relations.insert_conversion_relation({**relation, "converted_file_id": expired[1][0]})
    compression_relations.insert_compression_relation({**relation, "compressed_file_id": expired[2][0]})
    active = []
    for jobs in (ConversionJobDB(), CompressionJobDB()):
        for state in ("running", "queued"):
            identifier, path = retention_file(originals, 25)
            fields = {"user_id": "retention-fixture", "source_file_id": identifier}
            if isinstance(jobs, ConversionJobDB):
                fields["output_format"] = "pdf"
            job = jobs.insert_job(fields)
            if state == "running":
                assert jobs.claim_next_queued_job()["id"] == job["id"]
            with jobs.conn:
                jobs.conn.execute(f"UPDATE {jobs.TABLE_NAME} SET created_at = '2000-01-01 00:00:00' WHERE id = ?", (job["id"],))
            active.append((jobs, job["id"], identifier, path, state))
    missing_id, missing_path = retention_file(originals, 25)
    missing_path.unlink()
    cleanup_once()
    for db, (identifier, path) in zip((originals, conversions, compressions), expired, strict=True):
        assert db.get_file_metadata(identifier) is None and not path.exists()
    for db, (identifier, path) in zip((originals, conversions, compressions), recent, strict=True):
        assert db.get_file_metadata(identifier) is not None and path.exists()
    assert conversion_relations.get_original_from_conversion(expired[1][0]) is None
    assert compression_relations.get_original_from_compression(expired[2][0]) is None
    assert originals.get_file_metadata(missing_id) is None
    for jobs, job_id, identifier, path, state in active:
        assert originals.get_file_metadata(identifier) is not None and path.exists()
        assert jobs.get_job(job_id)["status"] == state
        jobs.mark_failed(job_id, "Synthetic acceptance finished")
    cleanup_once()
    assert all(not path.exists() for _, _, _, path, _ in active)
    print("24-hour cleanup expires uploads/conversions/compressions and relations; both queues protect queued/running sources")


def interleave_before_transaction(action):
    invoked = []

    def trace(statement):
        if statement.startswith("BEGIN") and not invoked:
            invoked.append(True)
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(action).result(timeout=10)

    return trace


def check_cleanup_admission_races():
    originals = FileDB()
    image = io.BytesIO()
    Image.new("RGB", (16, 16)).save(image, format="PNG")
    user = {"uuid": "retention-fixture"}
    for routes, job_type, request_type in (
        (conversion_jobs, ConversionJobDB, ConversionJobCreateRequest),
        (compression_jobs, CompressionJobDB, CompressionJobCreateRequest),
    ):
        for retry in (False, True):
            identifier, path = retention_file(originals, 25, image.getvalue(), "png")
            queue = job_type()
            fields = {"user_id": user["uuid"], "source_file_id": identifier}
            if job_type is ConversionJobDB:
                fields["output_format"] = "jpeg"
            if retry:
                job = queue.insert_job(fields)
                queue.mark_failed(job["id"], "Synthetic retry acceptance")
                submit = partial(routes.retry_job, job["id"], file_db=originals, job_db=queue, current_user=user)
            else:
                request_fields = {"id": identifier}
                if job_type is ConversionJobDB:
                    request_fields["output_format"] = "jpeg"
                submit = partial(routes.create_job, request_type(**request_fields), file_db=originals, job_db=queue, current_user=user)
            queue.conn.set_trace_callback(interleave_before_transaction(cleanup_once))
            try:
                try:
                    submit()
                except HTTPException as exc:
                    assert exc.status_code == 404, exc
                else:
                    raise AssertionError("Admission accepted a source that cleanup had already removed")
            finally:
                queue.conn.set_trace_callback(None)
            assert not path.exists()
            assert not any(row["source_file_id"] == identifier and row["status"] in {"queued", "running"} for row in queue.list_jobs())

        identifier, path = retention_file(originals, 23, image.getvalue(), "png")
        fields = {"user_id": user["uuid"], "source_file_id": identifier}
        if job_type is ConversionJobDB:
            fields["output_format"] = "jpeg"
        queue = job_type()
        job = queue.insert_job(fields)
        queue.mark_failed(job["id"], "Synthetic terminal retry acceptance")
        with queue.conn:
            queue.conn.execute(f"UPDATE {queue.TABLE_NAME} SET completed_at = '2000-01-01 00:00:00' WHERE id = ?", (job["id"],))
        retry_action = partial(routes.retry_job, job["id"], file_db=originals, job_db=queue, current_user=user)
        queue.conn.set_trace_callback(interleave_before_transaction(retry_action))
        try:
            job_cleanup_logic(queue)
        finally:
            queue.conn.set_trace_callback(None)
        assert queue.get_job(job["id"])["status"] == "queued" and path.exists()
        queue.cancel_queued_job(job["id"], user["uuid"])
    print("Cleanup/submission/retry interleavings reject expired inputs and preserve retried active jobs in both queues")


check_retention()
check_cleanup_admission_races()


with TestClient(create_app()) as client:
    assert client.get("/api/health/ready").status_code == 200
    password = "synthetic-image-test-password"
    response = client.post("/api/users", json={"username": "fixture", "password": password})
    assert response.status_code == 201, response.text
    response = client.post("/api/users/token", data={"username": "fixture", "password": password})
    assert response.status_code == 200, response.text
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    response = client.post("/api/users", headers=headers, json={"username": "member", "password": password, "role": "member"})
    assert response.status_code == 201, response.text
    response = client.post("/api/users/token", data={"username": "member", "password": password})
    assert response.status_code == 200, response.text
    member_headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get("/api/default-qualities", headers=member_headers).json() == {"defaults": []}
    assert client.get("/api/settings", headers=member_headers).json()["cleanup_ttl_minutes"] == 1440
    contents = io.BytesIO()
    Image.linear_gradient("L").resize((256, 256)).convert("RGB").save(contents, format="PNG")
    implicit_high = convert(client, member_headers, "new-member.png", contents.getvalue(), "jpeg")
    expected_high = convert(client, member_headers, "explicit-high.png", contents.getvalue(), "jpeg", quality="high")
    with Image.open(io.BytesIO(implicit_high)) as actual, Image.open(io.BytesIO(expected_high)) as expected:
        assert actual.quantization == expected.quantization
    explicit_low = convert(client, member_headers, "explicit-low.png", contents.getvalue(), "jpeg", quality="low")
    with Image.open(io.BytesIO(implicit_high)) as high, Image.open(io.BytesIO(explicit_low)) as low:
        assert sum(map(sum, high.quantization.values())) < sum(map(sum, low.quantization.values()))
    response = client.post("/api/files", headers=member_headers, files={"file": ("queued-default.png", contents.getvalue())})
    assert response.status_code == 200, response.text
    response = client.post("/api/jobs", headers=member_headers, json={"id": response.json()["metadata"]["id"], "output_format": "jpeg"})
    assert response.status_code == 201, response.text
    job = response.json()
    job_id = job["id"]
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        job = client.get(f"/api/jobs/{job_id}", headers=member_headers).json()
        if job["status"] in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job
    response = client.get(f"/api/files/{job['output_file_id']}", headers=member_headers)
    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(response.content)) as actual, Image.open(io.BytesIO(expected_high)) as expected:
        assert actual.quantization == expected.quantization
    print("New member without presets receives native High encoding through synchronous and queued APIs; explicit Low remains selectable")
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
