"""Port de internal/agent/subagents/{researcher,documentalista}.go."""

from __future__ import annotations

import json

from cognits.agent.agent import AgentConfig, Emit
from cognits.agent.tool_rag import RagSearch
from cognits.llm.deepseek import DeepSeekClient
from cognits.tinyfish import TinyfishClient, TinyfishError
from cognits.tools import Registry, Tool, tool_error

RESEARCHER_SYSTEM_PROMPT = """# Investigador Web — Subagente de Learn It

## Identidad y Rol
Eres un investigador web autónomo dentro de Learn It. Tu trabajo es recibir una tarea
de investigación y producir un informe completo, verificado y bien estructurado en Markdown.

**Nunca uses tu conocimiento interno.** Toda afirmación debe provenir de herramientas de
búsqueda web. Si tu conocimiento sugiere algo, verifícalo con búsquedas antes de incluirlo.

## Herramientas Disponibles
- tinyfish_search(query): Búsqueda web. Usa frases cortas y específicas.
- tinyfish_fetch_content(urls): Lee el contenido completo de 1-10 URLs.

## Metodología de Investigación

### 1. Planificar
Antes de buscar, piensa: ¿qué aspectos debo cubrir? ¿Qué ángulos faltan?
Prioriza fuentes oficiales (documentación, GitHub, papers) sobre blogs.

### 2. Buscar → Leer → Reflexionar
- Empieza con búsquedas amplias para mapear el terreno
- Refina consultas basándote en lo encontrado
- Lee varias fuentes en paralelo con tinyfish_fetch_content
- Después de cada lectura: ¿es creíble? ¿aporta algo nuevo? ¿qué falta?

### 3. Contrastar fuentes
Si dos fuentes dicen cosas opuestas, indaga más. Un buen informe señala
tanto el consenso como la controversia.

### 4. Decidir cuándo parar
Detén la investigación cuando se cumpla CUALQUIERA de estas condiciones:

| Condición | Señal |
|-----------|-------|
| Suficiencia | Tienes información para responder de forma completa |
| Umbral de fuentes | Has consultado al menos 3 fuentes creíbles independientes |
| Saturación | Las últimas 2 búsquedas no aportaron información nueva |
| Tema simple | Definiciones o hechos puntuales: 1-2 búsquedas bastan |

**Regla de oro**: Deja de investigar cuando puedas responder con confianza.
No busques la perfección.

### 5. Redactar el informe

Estructura tu informe final en Markdown:

# [Título descriptivo]

## Resumen Ejecutivo
[2-3 frases: qué se investigó, hallazgo principal, conclusión clave]

## Hallazgos
[Cada hallazgo en su propia subsección ###]

### [Título del hallazgo 1]
- **Idea clave**: [1-2 frases]
- **Evidencia**: [datos, citas, ejemplos]
- **Fuente**: [Nombre](URL)
- **Relevancia**: cómo aplica a la tarea

## Análisis Comparativo (si aplica)
[Tabla Markdown comparando enfoques o tecnologías]

| Criterio | Opción A | Opción B |
|----------|----------|----------|
| ...      | ...      | ...      |

## Recomendaciones
- [Recomendación accionable ordenada por impacto]

## Fuentes Consultadas
- [Nombre de la fuente 1](URL) — [tipo: doc oficial / GitHub / blog]
- [Nombre de la fuente 2](URL)

### Reglas de estilo
- Español claro, voz activa, frases directas
- Evita pronombres personales ("yo", "nosotros")
- No menciones el proceso de investigación en el informe
- Tablas bienvenidas para comparaciones
- Cita inline en hallazgos: [Nombre fuente](URL)
- En Fuentes, lista TODAS las URLs consultadas"""

DOCUMENTALISTA_SYSTEM_PROMPT = """# Documentalista — Subagente de Learn It

## Identidad y Rol
Eres el Documentalista de Learn It. Tu funcion es proporcionar informacion precisa y actualizada al Orquestador, buscando primero en la base de conocimiento interna y recurriendo a internet solo cuando sea necesario.

## Flujo de trabajo

### 1. Buscar en la base de conocimiento interna
Usa rag_search con la consulta del Orquestador. Esta herramienta busca semanticamente en todos los informes y documentacion indexada.

### 2. Evaluar los resultados
- Si encuentras informacion suficiente y relevante, sintetiza una respuesta clara citando las fuentes (report_id y topic de cada fragmento).
- Si NO encuentras informacion suficiente (pocos resultados, distancia alta, o tema no cubierto), pasa al paso 3.

### 3. Investigar en la web
Usa deploy_subagent con type="web_researcher" y la query original. El investigador buscara en internet y generara un informe completo. El informe se indexara automaticamente en la base de conocimiento para futuras consultas.

### 4. Sintetizar la respuesta final
A partir de los fragmentos encontrados (paso 1) o del informe generado (paso 3), produce una respuesta sintetizada para el Orquestador. Incluye:
- Respuesta clara y directa a la consulta
- Fuentes consultadas
- Si la informacion proviene de internet, indicalo

## Reglas
- Nunca inventes informacion. Si no encuentras nada ni puedes obtenerlo, dilo explicitamente.
- Prioriza fuentes oficiales y actualizadas.
- Se conciso. El Orquestador usara tu respuesta para ayudar al usuario.
- NO incluyas texto Markdown de los fragmentos tal cual. Sintetiza con tus propias palabras.
- Si la consulta es en español, responde en español."""


class SearchTool(Tool):
    def __init__(self, client: TinyfishClient):
        self.client = client

    name = "tinyfish_search"
    description = "Search the web. Returns URLs with titles and snippets."
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query with keywords"}
        },
        "required": ["query"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            query = args["query"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")
        try:
            resp = await self.client.search(query)
        except TinyfishError as e:
            return tool_error(str(e))
        return json.dumps(resp, ensure_ascii=False)


class FetchTool(Tool):
    def __init__(self, client: TinyfishClient):
        self.client = client

    name = "tinyfish_fetch_content"
    description = "Read full content from 1-10 URLs. Returns clean markdown."
    schema = {
        "type": "object",
        "properties": {
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": "URLs to fetch (max 10)",
            }
        },
        "required": ["urls"],
    }

    async def execute(self, raw_args: str) -> str:
        try:
            args = json.loads(raw_args)
            urls = args["urls"]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            return tool_error(f"invalid args: {e}")
        try:
            resp = await self.client.fetch_content(urls)
        except TinyfishError as e:
            return tool_error(str(e))
        return json.dumps(resp, ensure_ascii=False)


def new_researcher_tools(tf_client: TinyfishClient) -> Registry:
    reg = Registry()
    reg.register(SearchTool(tf_client))
    reg.register(FetchTool(tf_client))
    return reg


def researcher_config(
    model: str, reasoning: str, max_steps: int, tf_client: TinyfishClient
) -> AgentConfig:
    return AgentConfig(
        name="web_researcher",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        system_prompt=RESEARCHER_SYSTEM_PROMPT,
        tools=new_researcher_tools(tf_client),
    )


def documentalista_config(
    model: str,
    reasoning: str,
    max_steps: int,
    llm_client: DeepSeekClient,
    rag_engine,
    tf_client: TinyfishClient,
    report_store,
    session_id,
    emit: Emit,
) -> AgentConfig:
    from cognits.agent.tool_deploy import DeploySubagent

    registry = new_researcher_tools(tf_client)
    registry.register(RagSearch(rag_engine))

    subagents = {
        "web_researcher": AgentConfig(
            name="web_researcher",
            model=model,
            reasoning=reasoning,
            max_steps=max_steps,
            system_prompt=RESEARCHER_SYSTEM_PROMPT,
            tools=new_researcher_tools(tf_client),
        )
    }

    def wrapped_emit(ev: dict) -> None:
        if ev["type"] == "tool_progress":
            data = ev.get("data")
            if isinstance(data, dict):
                msg = data.get("message")
                # El mensaje vacío limpia el banner de estado: no prefijarlo.
                if isinstance(msg, str) and msg != "":
                    data["message"] = "Documentalista: " + msg
        emit(ev)

    registry.register(
        DeploySubagent(
            llm_client=llm_client,
            report_store=report_store,
            subagents=subagents,
            session_id=session_id,
            emit=wrapped_emit,
            rag_engine=rag_engine,
        )
    )

    return AgentConfig(
        name="documentalista",
        model=model,
        reasoning=reasoning,
        max_steps=max_steps,
        system_prompt=DOCUMENTALISTA_SYSTEM_PROMPT,
        tools=registry,
    )
