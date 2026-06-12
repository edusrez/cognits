package rag

import (
	"strings"
	"testing"
)

func TestSplitParagraphsKeepsFencesAtomic(t *testing.T) {
	md := "Intro.\n\n```go\nfunc main() {\n\n\tprintln(1)\n}\n```\n\nOutro."
	ps := splitParagraphs(md)
	if len(ps) != 3 {
		t.Fatalf("got %d paragraphs, want 3: %q", len(ps), ps)
	}
	// El fence con línea en blanco interior debe quedar entero en un párrafo.
	if !strings.HasPrefix(ps[1], "```go") || !strings.HasSuffix(ps[1], "```") {
		t.Errorf("fence partido o perdido: %q", ps[1])
	}
	if !strings.Contains(ps[1], "println(1)") {
		t.Errorf("contenido del fence perdido: %q", ps[1])
	}
}

func TestSplitParagraphsFenceWithoutBlankLines(t *testing.T) {
	md := "Texto.\n```py\nprint('hola')\n```\nSigue."
	ps := splitParagraphs(md)
	joined := strings.Join(ps, "|")
	if !strings.Contains(joined, "print('hola')") {
		t.Errorf("el código del fence sin líneas en blanco se perdió: %q", ps)
	}
}

func TestSplitMarkdownIndexesCode(t *testing.T) {
	md := "Explicación.\n\n```python\nprint('hola')\n```\n\nMás texto."
	chunks := SplitMarkdown(md, "r1", "tema")
	if len(chunks) == 0 {
		t.Fatal("sin chunks")
	}
	var all strings.Builder
	for i, c := range chunks {
		if c.ChunkIndex != i {
			t.Errorf("chunk %d con ChunkIndex %d", i, c.ChunkIndex)
		}
		if c.ReportID != "r1" || c.Topic != "tema" {
			t.Errorf("metadatos incorrectos: %+v", c)
		}
		all.WriteString(c.Text)
	}
	if !strings.Contains(all.String(), "print('hola')") {
		t.Error("el código fenced no quedó indexado en ningún chunk")
	}
}

func TestSplitMarkdownChunksLongInput(t *testing.T) {
	var sb strings.Builder
	for i := 0; i < 10; i++ {
		sb.WriteString(strings.Repeat("palabra ", 60))
		sb.WriteString("\n\n")
	}
	chunks := SplitMarkdown(sb.String(), "r2", "t")
	if len(chunks) < 2 {
		t.Fatalf("input de %d chars debería partirse en varios chunks, got %d", sb.Len(), len(chunks))
	}
	for _, c := range chunks {
		if strings.TrimSpace(c.Text) == "" {
			t.Error("chunk vacío")
		}
	}
}
