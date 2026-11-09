"""Identificación del plan, utilizable también en el API sin dependencias geométricas."""
import hashlib
import json

VERSION_COTAS = 'ciel-cotas-geometricas-v1'


def huella_plan(plan: dict) -> str:
    return hashlib.sha256(json.dumps(plan, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()
