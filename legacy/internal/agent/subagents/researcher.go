package subagents

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/eduardosrez/learnit/internal/tinyfish"
	"github.com/eduardosrez/learnit/internal/tools"
	"github.com/eduardosrez/learnit/internal/agent"
)

const researcherSystemPrompt = `# Investigador Web — Subagente de Learn It

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
- En Fuentes, lista TODAS las URLs consultadas`

func NewResearcherTools(tfClient *tinyfish.Client) *tools.Registry {
	reg := tools.NewRegistry()
	reg.Register(&searchTool{client: tfClient})
	reg.Register(&fetchTool{client: tfClient})
	return reg
}

type searchTool struct {
	client *tinyfish.Client
}

func (t *searchTool) Name() string        { return "tinyfish_search" }
func (t *searchTool) Description() string { return "Search the web. Returns URLs with titles and snippets." }
func (t *searchTool) Schema() json.RawMessage {
	return json.RawMessage(`{
		"type": "object",
		"properties": {
			"query": {"type": "string", "description": "Search query with keywords"}
		},
		"required": ["query"]
	}`)
}
func (t *searchTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var a struct {
		Query string `json:"query"`
	}
	if err := json.Unmarshal(args, &a); err != nil {
		return toolError(fmt.Sprintf("invalid args: %s", err.Error())), nil
	}
	resp, err := t.client.Search(ctx, a.Query)
	if err != nil {
		return toolError(err.Error()), nil
	}
	data, _ := json.Marshal(resp)
	return string(data), nil
}

type fetchTool struct {
	client *tinyfish.Client
}

func (t *fetchTool) Name() string        { return "tinyfish_fetch_content" }
func (t *fetchTool) Description() string { return "Read full content from 1-10 URLs. Returns clean markdown." }
func (t *fetchTool) Schema() json.RawMessage {
	return json.RawMessage(`{
		"type": "object",
		"properties": {
			"urls": {"type": "array", "items": {"type": "string"}, "description": "URLs to fetch (max 10)"}
		},
		"required": ["urls"]
	}`)
}
func (t *fetchTool) Execute(ctx context.Context, args json.RawMessage) (string, error) {
	var a struct {
		Urls []string `json:"urls"`
	}
	if err := json.Unmarshal(args, &a); err != nil {
		return toolError(fmt.Sprintf("invalid args: %s", err.Error())), nil
	}
	resp, err := t.client.FetchContent(ctx, a.Urls)
	if err != nil {
		return toolError(err.Error()), nil
	}
	data, _ := json.Marshal(resp)
	return string(data), nil
}

func toolError(msg string) string {
	data, _ := json.Marshal(map[string]string{"error": msg})
	return string(data)
}

func ResearcherConfig(model, reasoning string, maxSteps int, tfClient *tinyfish.Client) agent.AgentConfig {
	return agent.AgentConfig{
		Name:         "web_researcher",
		Model:        model,
		Reasoning:    reasoning,
		MaxSteps:     maxSteps,
		SystemPrompt: researcherSystemPrompt,
		Tools:        NewResearcherTools(tfClient),
	}
}
