# Cognits

**C**ontext-**O**riented **G**eneration for **N**eural **I**ntelligent **T**utoring **S**ystems.

Tutor personal multiagente con IA: un orquestador socrático coordina subagentes
(documentalista con RAG local, investigador web) para guiar tu aprendizaje desde
una interfaz web local, anclada a la carpeta del proyecto en el que estás
aprendiendo.

## Instalación

```bash
uv tool install cognits
```

> La instalación incluye el motor RAG local (onnxruntime + ChromaDB, ~600 MB).
> En el primer arranque se descarga el modelo de embeddings BGE-M3 (~2,3 GB).

## Uso

```bash
cd mi-proyecto-de-aprendizaje
cognits
```

Arranca un servidor local (puerto 5173 por defecto, variable `PORT`) y abre la
interfaz en el navegador. El estado vive en `./.cognits/` (sesiones, informes,
configuración con claves cifradas, índice RAG).

## Desarrollo

```bash
scripts/dev.sh    # Vite (HMR) + uvicorn --reload
scripts/build.sh  # build del frontend + wheel
uv run pytest
```

El frontend es una SPA SolidJS en `frontend/`; el backend es Python (FastAPI)
en `src/cognits/`.
