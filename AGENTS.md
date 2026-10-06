# Repository Guidelines

## Project Structure & Module Organization

- `aplicacion/`: FastAPI, SQLAlchemy, Celery, providers, campaigns, metrics; `calidad/` adds geometric planning, NVIDIA routing, reviews, and Quality Gate.
- `interfaz/src/`: React pages, Three.js viewer, and CSS themes; Vite builds into `interfaz/dist/`.
- `supervisor/` and `motores/`: isolated CAD execution and Docker images for CadQuery, build123d, and FreeCAD.
- `evaluador/`: geometry, topology, IoU, Chamfer, and deterministic multiview rendering.
- `datos/`: versioned prompts; `pruebas/`: tests and STEP fixtures. See `README_APLICACION.md` for operations and `PLAN_TECNICO_AGENTE_CIEL.md` for scope.

## Build, Test, and Development Commands

Run commands from the repository root. Build all services and CAD images, then start the application at `http://127.0.0.1:8000`:

```bash
docker compose --env-file /tmp/agente-ciel.env --profile imagenes build
docker compose --env-file /tmp/agente-ciel.env up -d
```

Install locked frontend dependencies and check the production build:

```bash
npm --prefix interfaz ci
npm --prefix interfaz run construir
```

Rebuild the application image and recreate `api` and `trabajador` after application changes; their source is baked into the image.

## Coding Style & Naming Conventions

Use Spanish identifiers, comments, UI text, tables, and columns; retain external API names. Python: four spaces, type hints, `snake_case` functions, `PascalCase` classes. JSX: two spaces, single quotes, semicolons, `camelCase` functions, `PascalCase` components. Match nearby code; no formatter or linter is configured.

## Testing Guidelines

Use `unittest`, `pruebas/test_*.py`, and `test_*` methods. Run the suites in their respective images:

```bash
docker run --rm --network agente-ciel_default -v "$PWD:/servicio:ro" ciel-aplicacion:piloto python -m unittest discover -s pruebas -v
docker run --rm -v "$PWD:/servicio:ro" ciel-evaluador:piloto python -m unittest discover -s pruebas -p test_evaluador.py -v
```

Geometry tests skip without CAD dependencies. Mock paid providers; use in-memory SQLite. Add regression tests and check UI changes in both themes and mobile layouts.

## Commit & Pull Request Guidelines

Use concise Spanish commit subjects (for example, `Implementar aplicación CAD y evaluación digital`); no prefix is established. PRs should describe behavior, validation, related issues, and include UI screenshots. Stage only relevant files.

## Configuration & Research Constraints

Keep `DEEPSEEK_API_KEY` and `NVIDIA_API_KEY` in an external file with mode `600`; never commit, log, print, or expose them to the frontend. Mock paid providers. Preserve the frozen 60 cases, five-attempt legacy loop, and separate technical/quality success. Never send STEP references to Planner, Modeler, or Repairer; reference metrics require the explicit flag. Version new protocols; do not rewrite historical campaigns.
