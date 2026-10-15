"""ZIP intake: unsafe archives are rejected, unsupported files are listed (never silently dropped)."""
import io, stat, unittest, zipfile

from intake import archive
from intake.archive import IntakeError, Limits, inventory

PDF = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n"


def make(members, compression=zipfile.ZIP_DEFLATED):
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", compression) as z:
        for item in members:
            if isinstance(item, zipfile.ZipInfo):
                z.writestr(item, b"target")
            else:
                name, data = item
                z.writestr(name, data)
    return bio.getvalue()


class SafeArchives(unittest.TestCase):
    def test_accepts_pdfs_and_lists_unsupported_and_ignored_files(self):
        inv = inventory(make([("C101.pdf", PDF), ("sub/Spec.PDF", PDF), ("notes.txt", b"hi"),
                              ("__MACOSX/._C101.pdf", b"x"), (".DS_Store", b"x"), ("noext", b"x")]))
        status = {e["filename"]: e["status"] for e in inv["entries"]}
        self.assertEqual(status["C101.pdf"], "accepted")
        self.assertEqual(status["sub/Spec.PDF"], "accepted")
        self.assertEqual(status["notes.txt"], "skipped_unsupported")
        self.assertEqual(status["noext"], "skipped_unsupported")
        self.assertEqual(status["__MACOSX/._C101.pdf"], "skipped_ignored")
        self.assertEqual(len(inv["entries"]), 6)  # nothing silently omitted
        self.assertTrue(all(e["reason"] for e in inv["entries"] if e["status"] != "accepted"))
        self.assertEqual(len(inv["archive_sha256"]), 64)
        self.assertEqual([n for n, _ in inv["documents"]], ["C101.pdf", "sub/Spec.PDF"])

    def test_stored_members_are_fine(self):
        self.assertEqual(len(inventory(make([("a.pdf", PDF)], zipfile.ZIP_STORED))["documents"]), 1)

    def test_client_supplied_extension_is_not_trusted(self):
        with self.assertRaises(IntakeError):
            inventory(make([("fake.pdf", b"MZ not a pdf at all")]))


class UnsafeArchives(unittest.TestCase):
    def rejects(self, data, limits=Limits()):
        with self.assertRaises(IntakeError):
            inventory(data, limits)

    def test_path_traversal_and_absolute_paths(self):
        for name in ("../evil.pdf", "a/../../evil.pdf", "..\\evil.pdf", "a\\..\\..\\evil.pdf", "/etc/x.pdf",
                     "\\abs.pdf", "C:\\Windows\\x.pdf", "c:/x.pdf", "ok/../../x.pdf"):
            with self.subTest(name=name):
                self.rejects(make([("good.pdf", PDF), (name, PDF)]))

    def test_control_characters_in_names(self):
        self.rejects(make([("a\x00.pdf", PDF)]))
        self.rejects(make([("a\n.pdf", PDF)]))

    def test_symlink_and_special_files(self):
        link = zipfile.ZipInfo("link.pdf")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        self.rejects(make([("good.pdf", PDF), link]))
        dev = zipfile.ZipInfo("dev.pdf")
        dev.external_attr = (stat.S_IFCHR | 0o666) << 16
        self.rejects(make([dev]))

    def test_nested_archive(self):
        self.rejects(make([("good.pdf", PDF), ("inner.zip", make([("x.pdf", PDF)]))]))
        self.rejects(make([("good.pdf", PDF), ("disguised.dat", make([("x.pdf", PDF)]))]))

    def test_duplicate_names_including_case_variants(self):
        self.rejects(make([("a.pdf", PDF), ("A.PDF", PDF)]))

    def test_encrypted_member(self):
        data = bytearray(make([("a.pdf", PDF)]))
        i = data.index(b"PK\x03\x04") + 6
        data[i] |= 0x01  # general-purpose bit 0 in the local header
        j = data.index(b"PK\x01\x02") + 8
        data[j] |= 0x01  # and in the central directory
        self.rejects(bytes(data))

    def test_decompression_bomb_by_ratio(self):
        self.rejects(make([("good.pdf", PDF), ("bomb.pdf", b"%PDF-" + b"\0" * 20_000_000)]))

    def test_size_ceilings(self):
        small = Limits(max_file_bytes=1000, max_total_bytes=5000, max_entries=3, max_archive_bytes=20000)
        self.rejects(make([("a.pdf", PDF + b"x" * 2000)]), small)                                  # per file
        self.rejects(make([(f"{i}.pdf", PDF + b"x" * 900) for i in range(3)]),
                     Limits(max_file_bytes=1000, max_total_bytes=2000))                             # total
        self.rejects(make([(f"{i}.pdf", PDF) for i in range(4)]), small)                           # entry count
        self.rejects(make([("a.pdf", PDF)]), Limits(max_archive_bytes=50))                          # archive size

    def test_header_that_lies_about_size_is_caught_by_counting_actual_bytes(self):
        data = bytearray(make([("a.pdf", PDF + b"x" * 5000)], zipfile.ZIP_STORED))
        # shrink the declared sizes in both headers so only streaming can notice
        for sig, off in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):
            i = data.index(sig) + off
            data[i:i + 4] = (100).to_bytes(4, "little")
        j = data.index(b"PK\x03\x04") + 18
        data[j:j + 4] = (100).to_bytes(4, "little")
        i = data.index(b"PK\x01\x02") + 20
        data[i:i + 4] = (100).to_bytes(4, "little")
        self.rejects(bytes(data))

    def test_not_a_zip_or_empty(self):
        for data in (b"", b"%PDF-1.4 not a zip", b"PK\x03\x04garbage", b"x" * 100):
            with self.subTest(data=data[:10]):
                self.rejects(data)

    def test_no_supported_documents(self):
        self.rejects(make([("readme.txt", b"hi"), ("image.png", b"\x89PNG")]))

    def test_non_bytes(self):
        for bad in (None, "text", 123):
            with self.assertRaises(IntakeError):
                inventory(bad)


class PdfIndexing(unittest.TestCase):
    def setUp(self):
        from intake import pdf_index
        if not pdf_index.available():
            self.skipTest("PyMuPDF not installed (requirements-pdf.txt)")
        self.pdf_index = pdf_index

    def build_pdf(self, pages, text="G1 CLEAR OPENING 4'-0\""):
        import pymupdf
        doc = pymupdf.open()
        for _ in range(pages):
            doc.new_page().insert_text((72, 72), text)
        return doc.tobytes()

    def test_index_pages_with_source_ids_and_text(self):
        inv = inventory(make([("F502.pdf", self.build_pdf(2))]))
        docs = self.pdf_index.index_documents(inv)
        self.assertEqual(len(docs), 1)
        d = docs[0]
        self.assertEqual(len(d["pages"]), 2)
        self.assertEqual(d["doc_id"], inv["entries"][0]["sha256"][:16])
        self.assertIn("CLEAR OPENING", d["pages"][0]["text"])
        self.assertEqual(d["pages"][1]["source_id"], f"{d['doc_id']}:p2")

    def test_corrupt_and_empty_pdfs_are_rejected(self):
        with self.assertRaises(IntakeError):
            self.pdf_index.index_pdf("bad.pdf", PDF + b"garbage", "id")
        with self.assertRaises(IntakeError):
            self.pdf_index.index_pdf("bad.pdf", b"%PDF-1.4\n", "id")

    def test_page_cap(self):
        with self.assertRaises(IntakeError):
            self.pdf_index.MAX_PAGES, old = 1, self.pdf_index.MAX_PAGES
            try:
                self.pdf_index.index_pdf("big.pdf", self.build_pdf(2), "id")
            finally:
                self.pdf_index.MAX_PAGES = old


if __name__ == "__main__":
    unittest.main()
