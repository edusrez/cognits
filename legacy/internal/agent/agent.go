package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/eduardosrez/learnit/internal/llm"
	"github.com/eduardosrez/learnit/internal/tools"
)

type Event struct {
	Type string      `json:"type"`
	Data interface{} `json:"data"`
}

type AgentConfig struct {
	Name         string
	Model        string
	Reasoning    string
	MaxSteps     int
	SystemPrompt string
	Tools        *tools.Registry
	Subagents    map[string]*AgentConfig
}

type Agent struct {
	Name         string
	Model        string
	Reasoning    string
	MaxSteps     int
	SystemPrompt string
	Tools        *tools.Registry
	Subagents    map[string]*AgentConfig
	llmClient    llm.Client
	Emit         func(Event)
}

func New(cfg AgentConfig, llmClient llm.Client) *Agent {
	return &Agent{
		Name:         cfg.Name,
		Model:        cfg.Model,
		Reasoning:    cfg.Reasoning,
		MaxSteps:     cfg.MaxSteps,
		SystemPrompt: cfg.SystemPrompt,
		Tools:        cfg.Tools,
		Subagents:    cfg.Subagents,
		llmClient:    llmClient,
		Emit:         func(Event) {},
	}
}

func (a *Agent) Run(ctx context.Context, messages []llm.Message, emit func(Event)) (string, error) {
	if a.SystemPrompt != "" {
		messages = append([]llm.Message{{Role: llm.RoleSystem, Content: a.SystemPrompt}}, messages...)
	}

	var toolDefs []llm.ToolDef
	if a.Tools != nil {
		for _, def := range a.Tools.Definitions() {
			toolDefs = append(toolDefs, llm.ToolDef{
				Type: def.Type,
				Function: llm.Function{
					Name:        def.Function.Name,
					Description: def.Function.Description,
					Parameters:  def.Function.Parameters,
				},
			})
		}
	}

	for iteration := 0; a.MaxSteps == 0 || iteration < a.MaxSteps; iteration++ {
		select {
		case <-ctx.Done():
			return "", fmt.Errorf("agent: cancelled after %d steps: %w", iteration, ctx.Err())
		default:
		}

		var contentBuilder strings.Builder
		var toolAccs map[int]*toolAccumulator
		var finishReason string

		err := a.llmClient.ChatCompletionStream(ctx, messages, toolDefs, a.Model, a.Reasoning, func(chunk llm.StreamChunk) {
			if len(chunk.Choices) == 0 {
				if chunk.Usage != nil {
					emit(Event{Type: "usage", Data: chunk.Usage})
				}
				return
			}
			delta := chunk.Choices[0].Delta

			if delta.Content != "" {
				contentBuilder.WriteString(delta.Content)
				emit(Event{Type: "token", Data: delta.Content})
			}
			if delta.ReasoningContent != "" {
				emit(Event{Type: "reasoning", Data: delta.ReasoningContent})
			}

			if len(delta.ToolCalls) > 0 {
				if toolAccs == nil {
					toolAccs = make(map[int]*toolAccumulator)
				}
				for _, tc := range delta.ToolCalls {
					acc := toolAccs[tc.Index]
					if acc == nil {
						acc = &toolAccumulator{}
						toolAccs[tc.Index] = acc
					}
					if tc.ID != "" {
						acc.ID = tc.ID
					}
					if tc.Type != "" {
						acc.Type = tc.Type
					}
					if tc.Function.Name != "" {
						acc.Name = tc.Function.Name
					}
					acc.ArgsBuilder.WriteString(tc.Function.Arguments)
				}
			}

			if chunk.Choices[0].FinishReason != "" {
				finishReason = chunk.Choices[0].FinishReason
			}

			if chunk.Usage != nil {
				emit(Event{Type: "usage", Data: chunk.Usage})
			}
		})
		if err != nil {
			return "", fmt.Errorf("agent: llm stream: %w", err)
		}

		content := contentBuilder.String()

		if len(toolAccs) == 0 || finishReason != "tool_calls" {
			return content, nil
		}

		assistantMsg := llm.Message{
			Role:    llm.RoleAssistant,
			Content: content,
		}

		// Los índices de tool calls pueden venir dispersos: iterar por claves
		// ordenadas en vez de asumir 0..len-1 (panic por nil).
		indices := make([]int, 0, len(toolAccs))
		for idx := range toolAccs {
			indices = append(indices, idx)
		}
		sort.Ints(indices)

		toolCalls := make([]llm.ToolCall, 0, len(toolAccs))
		for _, idx := range indices {
			acc := toolAccs[idx]
			toolCalls = append(toolCalls, llm.ToolCall{
				ID:   acc.ID,
				Type: "function",
				Function: llm.ToolCallFunction{
					Name:      acc.Name,
					Arguments: acc.ArgsBuilder.String(),
				},
			})
		}
		assistantMsg.ToolCalls = toolCalls
		messages = append(messages, assistantMsg)

		for _, tc := range toolCalls {
			tool, ok := a.Tools.Get(tc.Function.Name)
			if !ok {
				return "", fmt.Errorf("agent: unknown tool: %s", tc.Function.Name)
			}

			emit(Event{
				Type: "tool_start",
				Data: map[string]interface{}{
					"tool": tc.Function.Name,
					"args": tc.Function.Arguments,
					"id":   tc.ID,
				},
			})

			result, err := tool.Execute(ctx, json.RawMessage(tc.Function.Arguments))
			if err != nil {
				errJSON, _ := json.Marshal(map[string]string{"error": err.Error()})
				result = string(errJSON)
			}

			emit(Event{
				Type: "tool_end",
				Data: map[string]interface{}{
					"tool": tc.Function.Name,
					"id":   tc.ID,
				},
			})

			messages = append(messages, llm.Message{
				Role:       llm.RoleTool,
				Content:    result,
				ToolCallID: tc.ID,
			})
		}
	}

	return "", fmt.Errorf("agent: max steps reached (%d)", a.MaxSteps)
}

type toolAccumulator struct {
	ID          string
	Type        string
	Name        string
	ArgsBuilder strings.Builder
}
