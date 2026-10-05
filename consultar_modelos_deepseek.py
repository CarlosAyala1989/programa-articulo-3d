#!/usr/bin/env python3
"""Lista los modelos que devuelve el endpoint autenticado de DeepSeek."""

import getpass
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "https://api.deepseek.com/models"


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        api_key = getpass.getpass("DeepSeek API key (no se mostrará): ").strip()
    if not api_key:
        print("No se proporcionó una API key.", file=sys.stderr)
        return 2

    request = Request(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        method="GET",
    )
    del api_key

    try:
        with urlopen(request, timeout=20) as response:
            payload = json.loads(response.read(1_048_576))
    except HTTPError as exc:
        print(f"DeepSeek respondió HTTP {exc.code} al consultar /models.", file=sys.stderr)
        if exc.code == 401:
            print("La clave no fue aceptada. Revísala o crea una nueva.", file=sys.stderr)
        elif exc.code == 403:
            print("La clave no tiene permiso para consultar el catálogo.", file=sys.stderr)
        return 1
    except (URLError, TimeoutError) as exc:
        print(f"No se pudo conectar con DeepSeek: {getattr(exc, 'reason', exc)}", file=sys.stderr)
        return 1
    except (json.JSONDecodeError, UnicodeDecodeError):
        print("DeepSeek respondió con contenido que no es JSON válido.", file=sys.stderr)
        return 1

    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        print("La respuesta no contiene la lista esperada en el campo 'data'.", file=sys.stderr)
        return 1

    print(f"Modelos devueltos por DeepSeek ({len(models)}):")
    for model in sorted(models, key=lambda item: str(item.get("id", ""))):
        if not isinstance(model, dict):
            continue
        model_id = model.get("id", "(sin id)")
        name = model.get("name")
        modalities = ", ".join(model.get("input_modalities", [])) or "no informadas"
        context = model.get("context_window")
        output_limit = model.get("max_output_tokens")
        details = [f"entrada: {modalities}"]
        if context is not None:
            details.append(f"contexto: {context:,} tokens")
        if output_limit is not None:
            details.append(f"salida máxima: {output_limit:,} tokens")
        suffix = f" — {name}" if name and name != model_id else ""
        print(f"- {model_id}{suffix} ({'; '.join(details)})")
    print("\nEl catálogo confirma los IDs que la API anuncia para esta cuenta.")
    print("La autorización para generar y la cuota efectiva pueden variar por modelo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
