"""
Suite de pruebas unitarias y de integración para `html_processor` (Ejercicio 4).
Utiliza exclusivamente la librería estándar `unittest`.
"""

from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from html_processor.src.cli import main as cli_main
from html_processor.src.processor import (
    Base64ImageEncoder,
    HtmlFileDiscovery,
    HtmlImageProcessor,
    ImageEncodingError,
    ProcessingReport,
)

SAMPLE_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
EXPECTED_PNG_B64 = base64.b64encode(SAMPLE_PNG_BYTES).decode("ascii")


class TestHtmlImageProcessor(unittest.TestCase):
    """Pruebas exhaustivas para el procesamiento de HTML e imágenes a Base64."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="test_html_proc_")
        self.root = Path(self._tmp.name).resolve()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_encode_local_png_and_svg_success(self) -> None:
        img_path = self.root / "logo.png"
        img_path.write_bytes(SAMPLE_PNG_BYTES)
        html_dummy = self.root / "index.html"

        encoder = Base64ImageEncoder()
        uri = encoder.encode("logo.png?v=1.2#top", html_dummy)
        self.assertEqual(uri, f"data:image/png;base64,{EXPECTED_PNG_B64}")

    def test_encode_raises_on_missing_or_empty_or_remote_image(self) -> None:
        encoder = Base64ImageEncoder()
        html_dummy = self.root / "index.html"

        with self.assertRaises(ImageEncodingError):
            encoder.encode("no_existe.png", html_dummy)

        with self.assertRaises(ImageEncodingError):
            encoder.encode("   ", html_dummy)

        with self.assertRaises(ImageEncodingError):
            encoder.encode("https://example.com/remote.png", html_dummy)

    def test_recursive_directory_discovery_and_idempotency(self) -> None:
        sub1 = self.root / "nivel1"
        sub2 = sub1 / "nivel2"
        sub2.mkdir(parents=True)

        f1 = self.root / "a.html"
        f2 = sub1 / "b.htm"
        f3 = sub2 / "c.html"
        ignored = sub2 / "c.b64.html"
        txt = sub2 / "notas.txt"

        for f in (f1, f2, f3, ignored, txt):
            f.write_text("<html></html>", encoding="utf-8")

        discovery = HtmlFileDiscovery(output_suffix=".b64.html")
        found = discovery.discover([self.root])
        self.assertEqual(found, sorted([f1, f2, f3]))

    def test_end_to_end_processing_preserves_original_and_builds_report(self) -> None:
        img_dir = self.root / "images"
        sub_dir = self.root / "nested" / "deep"
        img_dir.mkdir(parents=True)
        sub_dir.mkdir(parents=True)

        valid_png = img_dir / "valid image.png"
        valid_png.write_bytes(SAMPLE_PNG_BYTES)

        valid_svg = img_dir / "badge.svg"
        svg_content = '<svg xmlns="http://www.w3.org/2000/svg"></svg>'
        valid_svg.write_text(svg_content, encoding="utf-8")
        expected_svg_b64 = base64.b64encode(svg_content.encode("utf-8")).decode("ascii")

        original_html_content = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "  <body>\n"
            "    <!-- Comentario preservado -->\n"
            '    <img src="images/valid%20image.png" alt="Con espacio" width="100">\n'
            '    <img src="images/missing.jpg" alt="No existe">\n'
            '    <img alt="Sin atributo src">\n'
            "  </body>\n"
            "</html>"
        )
        html_1 = self.root / "page1.html"
        html_1.write_text(original_html_content, encoding="utf-8")

        html_2_content = (
            "<html><body>"
            '<img src="../../images/badge.svg" />'
            '<img src="https://cdn.example.com/external.png" />'
            "</body></html>"
        )
        html_2 = sub_dir / "page2.html"
        html_2.write_text(html_2_content, encoding="utf-8")

        processor = HtmlImageProcessor(output_suffix=".b64.html")
        report = processor.process([html_1, self.root / "nested"])

        # 1. Verificar tipo y estructura del reporte {success: {}, fail: {}}
        self.assertIsInstance(report, ProcessingReport)
        self.assertIn("success", report)
        self.assertIn("fail", report)

        k1 = str(html_1)
        k2 = str(html_2)

        self.assertEqual(report["success"][k1], ["images/valid%20image.png"])
        self.assertEqual(
            report["fail"][k1],
            ["images/missing.jpg", "<img sin atributo src>"],
        )
        self.assertEqual(report["success"][k2], ["../../images/badge.svg"])
        self.assertEqual(report["fail"][k2], ["https://cdn.example.com/external.png"])

        # 2. Verificar que los archivos originales NO fueron modificados
        self.assertEqual(html_1.read_text(encoding="utf-8"), original_html_content)
        self.assertEqual(html_2.read_text(encoding="utf-8"), html_2_content)

        # 3. Verificar que los archivos nuevos fueron creados con el contenido Base64
        out_1 = self.root / "page1.b64.html"
        out_2 = sub_dir / "page2.b64.html"
        self.assertTrue(out_1.exists())
        self.assertTrue(out_2.exists())

        out_1_text = out_1.read_text(encoding="utf-8")
        self.assertIn(f'src="data:image/png;base64,{EXPECTED_PNG_B64}"', out_1_text)
        self.assertIn('src="images/missing.jpg"', out_1_text)
        self.assertIn("<!-- Comentario preservado -->", out_1_text)

        out_2_text = out_2.read_text(encoding="utf-8")
        self.assertIn(f'src="data:image/svg+xml;base64,{expected_svg_b64}"', out_2_text)

    def test_cli_demo_mode_outputs_valid_json(self) -> None:
        buf = io.StringIO()
        with redirect_stdout(buf):
            exit_code = cli_main(["--demo"])
        self.assertEqual(exit_code, 0)
        parsed = json.loads(buf.getvalue())
        self.assertIn("success", parsed)
        self.assertIn("fail", parsed)
        self.assertEqual(len(parsed["success"]), 2)
        self.assertEqual(len(parsed["fail"]), 1)


if __name__ == "__main__":
    unittest.main()

