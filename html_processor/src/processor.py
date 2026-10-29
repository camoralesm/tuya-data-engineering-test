"""
Motor orientado a objetos para descubrimiento de archivos HTML, extracción de etiquetas `<img>`,
codificación de imágenes a Data URI Base64 y generación no destructiva de documentos HTML.

Restricción técnica: Utiliza exclusivamente módulos built-in (Python Standard Library).
Principios aplicados: SOLID (SRP, OCP, LSP, ISP, DIP), PEP 8 y tipado estático PEP 484.
"""

from __future__ import annotations

import base64
import html
import logging
import mimetypes
import urllib.parse
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple, Union

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


class ImageEncodingError(Exception):
    """Excepción de dominio lanzada cuando una imagen no puede ser leída o codificada."""


class ProcessingReport(dict):
    """
    Objeto de resultado del procesamiento que extiende `dict` para ser directamente
    serializable a JSON con la estructura exacta requerida:
        {
            "success": { "<archivo_html>": ["<img_src_1>", ...] },
            "fail": { "<archivo_html>": ["<img_src_fallida_1>", ...] }
        }
    """

    def __init__(self) -> None:
        super().__init__(success={}, fail={})

    @property
    def success(self) -> Dict[str, List[str]]:
        return self["success"]

    @property
    def fail(self) -> Dict[str, List[str]]:
        return self["fail"]

    def record_success(self, html_key: str, image_src: str) -> None:
        """Registra una imagen procesada exitosamente para un archivo HTML dado."""
        self["success"].setdefault(html_key, []).append(image_src)

    def record_failure(self, html_key: str, image_src: str) -> None:
        """Registra una imagen cuyo procesamiento falló para un archivo HTML dado."""
        self["fail"].setdefault(html_key, []).append(image_src)

    def to_dict(self) -> Dict[str, Dict[str, List[str]]]:
        """Retorna una copia pura tipo `dict` del reporte."""
        return {
            "success": dict(self["success"]),
            "fail": dict(self["fail"]),
        }


class ImageEncoderStrategy(ABC):
    """
    Interfaz abstracta (DIP / OCP) para estrategias de resolución y codificación de imágenes.
    """

    @abstractmethod
    def encode(self, img_src: str, html_file_path: Path) -> str:
        """
        Resuelve `img_src` relativo a `html_file_path` y retorna un string Data URI en Base64.
        Lanza `ImageEncodingError` si el recurso no es válido o no puede leerse.
        """


class Base64ImageEncoder(ImageEncoderStrategy):
    """
    Implementación estándar que convierte archivos de imagen locales a Data URI Base64
    (`data:<mime_type>;base64,<payload>`).
    """

    FALLBACK_MIME_TYPES: Dict[str, str] = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
        ".ico": "image/x-icon",
    }

    def encode(self, img_src: str, html_file_path: Path) -> str:
        cleaned_src = (img_src or "").strip()
        if not cleaned_src:
            raise ImageEncodingError("El atributo 'src' de la etiqueta <img> está vacío.")

        if cleaned_src.startswith("data:"):
            # Ya se encuentra codificada en Base64 / Data URI
            return cleaned_src

        parsed = urllib.parse.urlparse(cleaned_src)
        if parsed.scheme in {"http", "https", "ftp"}:
            raise ImageEncodingError(
                f" Esquema remoto no soportado para resolución local offline: {cleaned_src}"
            )

        # Decodificar caracteres escapados en URL (ej. '%20' -> espacio) e ignorar query/fragment
        raw_path_str = urllib.parse.unquote(parsed.path)
        if not raw_path_str:
            raise ImageEncodingError(f"Ruta de imagen inválida en src='{cleaned_src}'.")

        candidate_path = Path(raw_path_str)
        if not candidate_path.is_absolute():
            candidate_path = (html_file_path.parent / candidate_path).resolve()

        if not candidate_path.exists() or not candidate_path.is_file():
            raise ImageEncodingError(f"Archivo de imagen no encontrado: {candidate_path}")

        mime_type = self._guess_mime_type(candidate_path)
        try:
            binary_data = candidate_path.read_bytes()
        except OSError as exc:
            raise ImageEncodingError(
                f"Error de E/S leyendo la imagen '{candidate_path}': {exc}"
            ) from exc

        b64_payload = base64.b64encode(binary_data).decode("ascii")
        return f"data:{mime_type};base64,{b64_payload}"

    def _guess_mime_type(self, file_path: Path) -> str:
        guessed, _ = mimetypes.guess_type(str(file_path))
        if guessed:
            return guessed
        ext = file_path.suffix.lower()
        return self.FALLBACK_MIME_TYPES.get(ext, "application/octet-stream")


class _HtmlImgRewriterParser(HTMLParser):
    """
    Parser HTML basado en eventos (built-in `html.parser.HTMLParser`) que reconstruye
    el documento preservando su estructura original y reemplazando únicamente el atributo
    `src` de las etiquetas `<img>` cuando la codificación a Base64 es exitosa.
    """

    def __init__(
        self,
        html_file_path: Path,
        html_report_key: str,
        encoder: ImageEncoderStrategy,
        report: ProcessingReport,
    ) -> None:
        super().__init__(convert_charrefs=False)
        self._html_file_path = html_file_path
        self._html_report_key = html_report_key
        self._encoder = encoder
        self._report = report
        self._chunks: List[str] = []

    def get_transformed_html(self) -> str:
        return "".join(self._chunks)

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "img":
            self._chunks.append(self._process_img_tag(tag, attrs, is_self_closing=False))
        else:
            self._chunks.append(self.get_starttag_text() or self._rebuild_tag(tag, attrs, False))

    def handle_startendtag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag.lower() == "img":
            self._chunks.append(self._process_img_tag(tag, attrs, is_self_closing=True))
        else:
            self._chunks.append(self.get_starttag_text() or self._rebuild_tag(tag, attrs, True))

    def handle_endtag(self, tag: str) -> None:
        self._chunks.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self._chunks.append(data)

    def handle_comment(self, data: str) -> None:
        self._chunks.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._chunks.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._chunks.append(f"<?{data}>")

    def handle_entityref(self, name: str) -> None:
        self._chunks.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._chunks.append(f"&#{name};")

    def _process_img_tag(
        self,
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
        is_self_closing: bool,
    ) -> str:
        attr_names = [k.lower() for k, _ in attrs]
        if "src" not in attr_names:
            self._report.record_failure(self._html_report_key, "<img sin atributo src>")
            return self._rebuild_tag(tag, attrs, is_self_closing)

        new_attrs: List[Tuple[str, Optional[str]]] = []
        for attr_name, attr_val in attrs:
            if attr_name.lower() == "src":
                original_src = attr_val if attr_val is not None else ""
                try:
                    data_uri = self._encoder.encode(original_src, self._html_file_path)
                    self._report.record_success(self._html_report_key, original_src)
                    new_attrs.append((attr_name, data_uri))
                except ImageEncodingError as exc:
                    logger.warning(
                        "Fallo al codificar imagen '%s' en '%s': %s",
                        original_src,
                        self._html_file_path,
                        exc,
                    )
                    self._report.record_failure(self._html_report_key, original_src)
                    new_attrs.append((attr_name, attr_val))
            else:
                new_attrs.append((attr_name, attr_val))

        return self._rebuild_tag(tag, new_attrs, is_self_closing)

    @staticmethod
    def _rebuild_tag(
        tag: str,
        attrs: List[Tuple[str, Optional[str]]],
        is_self_closing: bool,
    ) -> str:
        parts: List[str] = [f"<{tag}"]
        for key, val in attrs:
            if val is None:
                parts.append(f" {key}")
            else:
                escaped_val = html.escape(val, quote=True)
                parts.append(f' {key}="{escaped_val}"')
        parts.append(" />" if is_self_closing else ">")
        return "".join(parts)


class HtmlFileDiscovery:
    """
    Servicio de descubrimiento de archivos HTML a partir de una colección mixta
    de rutas de archivos o directorios (incluyendo subdirectorios recursivamente).
    """

    VALID_EXTENSIONS: Set[str] = {".html", ".htm"}

    def __init__(self, output_suffix: str = ".b64.html") -> None:
        self._output_suffix = output_suffix.lower()

    def discover(self, inputs: Union[PathLike, Iterable[PathLike]]) -> List[Path]:
        if isinstance(inputs, (str, Path)):
            input_list: Sequence[PathLike] = [inputs]
        else:
            input_list = list(inputs)

        discovered: List[Path] = []
        seen: Set[Path] = set()

        for item in input_list:
            path = Path(item).resolve()
            if not path.exists():
                logger.warning("La ruta especificada no existe y será omitida: %s", path)
                continue

            if path.is_file():
                if self._is_target_html(path) and path not in seen:
                    seen.add(path)
                    discovered.append(path)
            elif path.is_dir():
                for child in sorted(path.rglob("*")):
                    if child.is_file() and self._is_target_html(child) and child not in seen:
                        seen.add(child)
                        discovered.append(child)

        return discovered

    def _is_target_html(self, file_path: Path) -> bool:
        name_lower = file_path.name.lower()
        if name_lower.endswith(self._output_suffix):
            # Evitar reprocesar archivos ya generados por la herramienta
            return False
        return file_path.suffix.lower() in self.VALID_EXTENSIONS


class HtmlImageProcessor:
    """
    Fachada principal para procesar lotes de archivos y directorios HTML,
    reemplazar imágenes por su representación en Base64 creando nuevos archivos
    (sin sobrescribir los originales) y retornar el reporte consolidado `{success: {}, fail: {}}`.
    """

    def __init__(
        self,
        encoder: Optional[ImageEncoderStrategy] = None,
        output_suffix: str = ".b64.html",
        output_dir: Optional[PathLike] = None,
    ) -> None:
        if not output_suffix or not output_suffix.strip():
            raise ValueError("El sufijo de salida (output_suffix) no puede estar vacío.")
        self._encoder: ImageEncoderStrategy = encoder or Base64ImageEncoder()
        self._output_suffix = output_suffix
        self._output_dir = Path(output_dir).resolve() if output_dir else None
        self._discovery = HtmlFileDiscovery(output_suffix=output_suffix)

    def process(self, inputs: Union[PathLike, Iterable[PathLike]]) -> ProcessingReport:
        """
        Procesa un listado de archivos HTML o directorios (incluyendo subdirectorios),
        crea un archivo HTML nuevo por cada archivo procesado y retorna el objeto
        `ProcessingReport` con llaves `success` y `fail`.
        """
        report = ProcessingReport()
        html_files = self._discovery.discover(inputs)

        for html_file in html_files:
            self._process_single_file(html_file, report)

        return report

    def build_output_path(self, original_html_path: Path) -> Path:
        """
        Determina la ruta del nuevo archivo HTML garantizando que jamás se sobrescriba
        el archivo original.
        """
        stem = original_html_path.stem
        new_name = f"{stem}{self._output_suffix}"
        if self._output_dir is not None:
            self._output_dir.mkdir(parents=True, exist_ok=True)
            candidate = (self._output_dir / new_name).resolve()
        else:
            candidate = (original_html_path.parent / new_name).resolve()

        if candidate == original_html_path.resolve():
            candidate = original_html_path.with_name(f"{stem}.copy{self._output_suffix}")
        return candidate

    def _process_single_file(self, html_path: Path, report: ProcessingReport) -> Path:
        html_key = str(html_path)
        try:
            raw_html = html_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raw_html = html_path.read_text(encoding="latin-1")

        parser = _HtmlImgRewriterParser(
            html_file_path=html_path,
            html_report_key=html_key,
            encoder=self._encoder,
            report=report,
        )
        parser.feed(raw_html)
        parser.close()

        transformed_html = parser.get_transformed_html()
        output_path = self.build_output_path(html_path)
        output_path.write_text(transformed_html, encoding="utf-8")
        logger.info("Archivo procesado: %s -> %s", html_path.name, output_path.name)
        return output_path

