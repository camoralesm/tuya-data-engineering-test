"""
Paquete `html_processor`: Procesamiento orientado a objetos de archivos HTML
para incrustación de imágenes en Base64 utilizando únicamente la librería estándar de Python.
"""

from .processor import (
    Base64ImageEncoder,
    HtmlFileDiscovery,
    HtmlImageProcessor,
    ImageEncodingError,
    ProcessingReport,
)

__all__ = [
    "Base64ImageEncoder",
    "HtmlFileDiscovery",
    "HtmlImageProcessor",
    "ImageEncodingError",
    "ProcessingReport",
]

