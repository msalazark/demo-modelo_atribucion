from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import ValidationError

from .esquema import ConfigCliente

BASE = Path(__file__).resolve().parent.parent


def cargar_config(ruta: str | Path = "config/demo.yaml") -> ConfigCliente:
    """Lee un YAML de configuración y lo valida con ConfigCliente.

    Las rutas relativas se resuelven contra la raíz del repositorio, no contra el cwd,
    para que `streamlit run dashboard.py` y `python run_demo.py` usen el mismo archivo
    sin depender de desde dónde se invoquen.
    """
    ruta = Path(ruta)
    if not ruta.is_absolute():
        ruta = BASE / ruta
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de configuración: {ruta}")
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    try:
        return ConfigCliente(**datos)
    except ValidationError as e:
        campos = ", ".join(".".join(str(p) for p in err["loc"]) for err in e.errors())
        raise ValueError(f"Configuración inválida en {ruta} — revisa: {campos}\n{e}") from e
