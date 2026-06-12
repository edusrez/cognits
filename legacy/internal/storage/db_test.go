package storage

import "testing"

func TestBuildFTS5Query(t *testing.T) {
	cases := []struct {
		name string
		in   string
		want string
	}{
		{"una palabra", "golang", `"golang"*`},
		{"varias palabras", "go routines", `"go"* "routines"*`},
		{"comilla interior escapada", `fo"o`, `"fo""o"*`},
		{"operadores FTS neutralizados", "go AND rust", `"go"* "AND"* "rust"*`},
		{"parentesis y asterisco recortados", "(term)*", `"term"*`},
		{"solo simbolos", `()*`, ""},
		{"vacio", "", ""},
		{"espacios", "   ", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := buildFTS5Query(tc.in); got != tc.want {
				t.Errorf("buildFTS5Query(%q) = %q, want %q", tc.in, got, tc.want)
			}
		})
	}
}

func TestEscapeLike(t *testing.T) {
	cases := []struct{ in, want string }{
		{"plain", "plain"},
		{"100%", `100\%`},
		{"a_b", `a\_b`},
		{`back\slash`, `back\\slash`},
	}
	for _, tc := range cases {
		if got := escapeLike(tc.in); got != tc.want {
			t.Errorf("escapeLike(%q) = %q, want %q", tc.in, got, tc.want)
		}
	}
}
