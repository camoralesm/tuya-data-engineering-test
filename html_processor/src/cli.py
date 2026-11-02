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


def run_demo(target_dir: Optional[Path] = None) -> int:
    """
    Ejecuta una demostración autocontenida generando archivos HTML originales y
    sus versiones con imágenes incrustadas en Base64 (.b64.html) dentro de
    `html_processor/sample_output/`, mostrando el JSON resultante.
    """
    root = (
        target_dir.resolve()
        if target_dir is not None
        else (Path(__file__).resolve().parents[1] / "sample_output")
    )
    assets = root / "assets"
    sub = root / "sub_pages"
    assets.mkdir(parents=True, exist_ok=True)
    sub.mkdir(parents=True, exist_ok=True)

    png_path = assets / "logo_tuya.png"
    png_path.write_bytes(_TINY_PNG_BYTES)

    svg_path = assets / "icon.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="120" height="40">'
        '<rect width="120" height="40" rx="8" fill="#E30613"/>'
        '<text x="60" y="25" font-family="Arial" font-size="16" font-weight="bold" '
        'fill="#FFFFFF" text-anchor="middle">TUYA S.A.</text></svg>',
        encoding="utf-8",
    )

    html_main = root / "index.html"
    html_main.write_text(
        "<!DOCTYPE html>\n"
        '<html lang="es"><head><meta charset="utf-8"><title>Demo Tuya Base64</title></head>\n'
        '<body style="font-family: sans-serif; padding: 24px;">\n'
        "  <h1>Portal Tuya - Prueba de Imágenes Base64</h1>\n"
        '  <p>1. Imagen PNG convertida exitosamente a Base64:</p>\n'
        '  <img src="assets/logo_tuya.png" alt="Logo Tuya PNG" width="48" height="48" style="border:1px solid #ccc;">\n'
        '  <p>2. Imagen rota (reportada en fail sin detener el proceso):</p>\n'
        '  <img src="assets/missing_banner.jpg" alt="Banner Faltante">\n'
        '  <p><a href="sub_pages/detalle.b64.html">Ver subpágina con SVG en Base64</a></p>\n'
        "</body></html>\n",
        encoding="utf-8",
    )

    html_sub = sub / "detalle.html"
    html_sub.write_text(
        "<!DOCTYPE html>\n"
        '<html lang="es"><head><meta charset="utf-8"><title>Detalle SVG Base64</title></head>\n'
        '<body style="font-family: sans-serif; padding: 24px;">\n'
        "  <h2>Subpágina con Icono SVG incrustado en Base64</h2>\n"
        '  <img src="../assets/icon.svg" class="icon" />\n'
        '  <p><a href="../index.b64.html">Volver al inicio</a></p>\n'
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

