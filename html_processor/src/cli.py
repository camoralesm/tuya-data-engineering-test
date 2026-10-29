#!/usr/bin/env python3
"""
Interfaz de Línea de Comandos (CLI) para `html_processor`.

Permite ejecutar el procesador pasándole rutas de archivos HTML o directorios,
o bien correr una demostración autocontenida mediante el flag `--demo`.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from html_processor.src.processor import HtmlImageProcessor
else:
    from .processor import HtmlImageProcessor


# PNG transparente minimalista de 1x1 píxel para el modo demostración
_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


def run_demo() -> int:
    """
    Ejecuta una demostración autocontenida en un directorio temporal con subdirectorios,
    imágenes válidas (PNG, SVG) e imágenes rotas/inexistentes, mostrando el JSON resultante.
    """
    with tempfile.TemporaryDirectory(prefix="tuya_html_demo_") as tmp_dir:
        root = Path(tmp_dir)
        assets = root / "assets"
        sub = root / "sub_pages"
        assets.mkdir(parents=True, exist_ok=True)
        sub.mkdir(parents=True, exist_ok=True)

        png_path = assets / "logo_tuya.png"
        png_path.write_bytes(_TINY_PNG_BYTES)

        svg_path = assets / "icon.svg"
        svg_path.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">'
            '<circle cx="5" cy="5" r="4" fill="red"/></svg>',
            encoding="utf-8",
        )

        html_main = root / "index.html"
        html_main.write_text(
            "<!DOCTYPE html>\n"
            "<html><body>\n"
            '  <h1>Portal Tuya</h1>\n'
            '  <img src="assets/logo_tuya.png" alt="Logo Tuya">\n'
            '  <img src="assets/missing_banner.jpg" alt="Banner Faltante">\n'
            "</body></html>\n",
            encoding="utf-8",
        )

        html_sub = sub / "detalle.html"
        html_sub.write_text(
            "<!DOCTYPE html>\n"
            "<html><body>\n"
            '  <img src="../assets/icon.svg" class="icon" />\n'
            "</body></html>\n",
            encoding="utf-8",
        )

        processor = HtmlImageProcessor(output_suffix=".b64.html")
        report = processor.process([root])

        print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Procesa archivos HTML o directorios recursivamente y reemplaza las imágenes "
            "asociadas (<img src=...>) por su codificación en Base64 creando archivos nuevos."
        )
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Listado de rutas de archivos HTML o directorios a procesar.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directorio opcional donde se guardarán los nuevos archivos HTML generados.",
    )
    parser.add_argument(
        "--suffix",
        default=".b64.html",
        help="Sufijo para los nuevos archivos HTML creados (default: .b64.html).",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Ejecuta una demostración autocontenida e imprime el objeto de salida.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Habilita logs detallados en consola.",
    )

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.ERROR,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
    )

    if args.demo:
        return run_demo()

    if not args.paths:
        parser.error("Debe proporcionar al menos una ruta (archivo o directorio) o usar --demo.")

    processor = HtmlImageProcessor(
        output_suffix=args.suffix,
        output_dir=args.output_dir,
    )
    report = processor.process(args.paths)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

