"""Configuración por cliente y modo de ejecución (RQ-01).

`cargar_config()` lee un YAML de este directorio y lo valida con `ConfigCliente`.
"""
from .cargar import cargar_config
from .esquema import ConfigCliente

__all__ = ["ConfigCliente", "cargar_config"]
