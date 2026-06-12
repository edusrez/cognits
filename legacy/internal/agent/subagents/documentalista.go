package subagents

import (
	"github.com/eduardosrez/learnit/internal/agent"
	"github.com/eduardosrez/learnit/internal/agent/tools"
	"github.com/eduardosrez/learnit/internal/llm"
	"github.com/eduardosrez/learnit/internal/rag"
	"github.com/eduardosrez/learnit/internal/storage"
	"github.com/eduardosrez/learnit/internal/tinyfish"
)

const documentalistaSystemPrompt = `# Documentalista — Subagente de Learn It

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
- Si la consulta es en español, responde en español.`

func DocumentalistaConfig(
	model, reasoning string,
	maxSteps int,
	llmClient llm.Client,
	ragClient *rag.Client,
	tfClient *tinyfish.Client,
	reportStore *storage.ReportStore,
	subagentCfgs map[string]storage.SubagentConfig,
	sessionID func() string,
	emit func(agent.Event),
) *agent.AgentConfig {
	registry := NewResearcherTools(tfClient)
	registry.Register(tools.NewRagSearch(ragClient))

	subagents := map[string]*agent.AgentConfig{
		"web_researcher": {
			Name:         "web_researcher",
			Model:        model,
			Reasoning:    reasoning,
			MaxSteps:     maxSteps,
			SystemPrompt: researcherSystemPrompt,
			Tools:        NewResearcherTools(tfClient),
		},
	}

	wrappedEmit := func(ev agent.Event) {
		if ev.Type == "tool_progress" {
			if data, ok := ev.Data.(map[string]interface{}); ok {
				// El mensaje vacío limpia el banner de estado: no prefijarlo.
				if msg, ok := data["message"].(string); ok && msg != "" {
					data["message"] = "Documentalista: " + msg
				}
			}
		}
		emit(ev)
	}

	registry.Register(&tools.DeploySubagent{
		LLMClient:   llmClient,
		ReportStore: reportStore,
		Subagents:   subagents,
		SessionID:   sessionID,
		Emit:        wrappedEmit,
		RagClient:   ragClient,
	})

	return &agent.AgentConfig{
		Name:         "documentalista",
		Model:        model,
		Reasoning:    reasoning,
		MaxSteps:     maxSteps,
		SystemPrompt: documentalistaSystemPrompt,
		Tools:        registry,
	}
}
