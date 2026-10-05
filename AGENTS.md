# Repository Guidelines

## Project Structure & Module Organization

- `aplicacion/`: FastAPI endpoints, SQLAlchemy models, Celery jobs, AI providers, prompts, campaigns, and metrics.
- `interfaz/src/`: React pages, Three.js viewer, and CSS themes; Vite builds into `interfaz/dist/`.
- `supervisor/` and `motores/`: isolated CAD execution and Docker images for CadQuery, build123d, and FreeCAD.
- `evaluador/`: independent geometry, topology, IoU, and Chamfer evaluation.
- `datos/`: versioned prompts; `pruebas/`: tests and STEP fixtures. Consult `README_APLICACION.md` for operations and `PLAN_TECNICO_AGENTE_CIEL.md` for scope.

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

Use Spanish identifiers, comments, UI text, tables, and columns; retain required external API names. Python uses four-space indentation, type hints, `snake_case` functions, and `PascalCase` classes. JSX uses two spaces, single quotes, semicolons, `camelCase` functions, and `PascalCase` components. Match surrounding code; no formatter or linter is configured.

## Testing Guidelines

Use `unittest` with `pruebas/test_*.py` files and `test_*` methods. Run the application suite and geometry suite in their respective images:

```bash
docker run --rm --network agente-ciel_default -v "$PWD:/servicio:ro" ciel-aplicacion:piloto python -m unittest discover -s pruebas -v
docker run --rm -v "$PWD:/servicio:ro" ciel-evaluador:piloto python -m unittest discover -s pruebas -p test_evaluador.py -v
```

Geometry tests skip without CAD dependencies. Mock paid providers; use in-memory SQLite for database tests. No coverage threshold is configured. Add regression tests for changed behavior and check UI changes in both themes and mobile layouts.

## Commit & Pull Request Guidelines

Recent commits use concise Spanish subjects such as `Documentar plan y prototipos del estudio CAD` and `Implementar aplicación CAD y evaluación digital`; no prefix convention is established. PRs should explain the problem, behavior changes, validation, related issues, and screenshots for UI changes. Stage only relevant files.

## Configuration & Research Constraints

Keep `DEEPSEEK_API_KEY` in an external environment file with permissions `600`; never commit or print secrets. Preserve the frozen 60-case dataset through versioning, the five-attempt closed-loop limit, and separate execution/CAD success metrics. Never send independent STEP references to AI providers.
