package rag

import (
	"fmt"
	"strings"
	"unicode/utf8"
)

const (
	chunkSize    = 1600
	chunkOverlap = 160
)

// splitParagraphs separa por líneas en blanco, pero trata cada bloque fenced
// (``` ... ```) como un párrafo atómico: el split ciego por "\n\n" perdía los
// fences sin líneas en blanco y filtraba código suelto sin contexto cuando
// las tenían.
func splitParagraphs(md string) []string {
	var paragraphs []string
	var current []string
	inFence := false

	flush := func() {
		if len(current) == 0 {
			return
		}
		p := strings.TrimSpace(strings.Join(current, "\n"))
		if p != "" {
			paragraphs = append(paragraphs, p)
		}
		current = nil
	}

	for _, line := range strings.Split(md, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "```") {
			if !inFence {
				flush()
				inFence = true
				current = append(current, line)
			} else {
				current = append(current, line)
				flush()
				inFence = false
			}
			continue
		}
		if inFence {
			current = append(current, line)
			continue
		}
		if trimmed == "" {
			flush()
			continue
		}
		current = append(current, line)
	}
	flush()
	return paragraphs
}

func SplitMarkdown(md string, reportID, topic string) []ChunkInput {
	paragraphs := splitParagraphs(md)
	var chunks []ChunkInput

	var current []string
	currentLen := 0
	idx := 0

	flush := func() {
		if len(current) == 0 {
			return
		}
		text := strings.Join(current, "\n\n")
		text = strings.TrimSpace(text)
		if text == "" {
			current = nil
			currentLen = 0
			return
		}
		chunks = append(chunks, ChunkInput{
			ID:         fmt.Sprintf("%s_c%d", reportID, idx),
			Text:       text,
			ReportID:   reportID,
			SourceType: "web",
			ChunkIndex: idx,
			Topic:      topic,
		})
		idx++

		overlapStart := len(current) - overlapCount(current, chunkOverlap)
		if overlapStart <= 0 {
			current = nil
			currentLen = 0
			return
		}
		overlap := current[overlapStart:]
		current = overlap
		currentLen = 0
		for _, p := range current {
			currentLen += utf8.RuneCountInString(p)
		}
	}

	for _, p := range paragraphs {
		pLen := utf8.RuneCountInString(p)
		if currentLen+pLen > chunkSize && len(current) > 0 {
			flush()
		}
		current = append(current, p)
		currentLen += pLen
	}
	flush()

	return chunks
}

func overlapCount(paragraphs []string, targetChars int) int {
	count := 0
	chars := 0
	for i := len(paragraphs) - 1; i >= 0; i-- {
		chars += utf8.RuneCountInString(paragraphs[i])
		count++
		if chars >= targetChars {
			break
		}
	}
	return count
}
