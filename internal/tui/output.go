package tui

import (
	"fmt"
	"os"
	"strings"

	"github.com/charmbracelet/lipgloss"
	"github.com/jedib0t/go-pretty/v6/table"
	"github.com/jedib0t/go-pretty/v6/text"
)

var (
	styleSuccess = lipgloss.NewStyle().Foreground(lipgloss.Color("2"))  // green
	styleError   = lipgloss.NewStyle().Foreground(lipgloss.Color("1"))  // red
	styleWarning = lipgloss.NewStyle().Foreground(lipgloss.Color("3"))  // yellow
	styleInfo    = lipgloss.NewStyle().Foreground(lipgloss.Color("6"))  // cyan
	styleDim     = lipgloss.NewStyle().Foreground(lipgloss.Color("8"))  // dark grey
	styleBold    = lipgloss.NewStyle().Bold(true)
)

func Success(msg string) {
	fmt.Println(styleSuccess.Render("✓") + " " + msg)
}

func Error(msg string) {
	fmt.Fprintln(os.Stderr, styleError.Render("✗")+" "+styleError.Render(msg))
}

func Warning(msg string) {
	fmt.Fprintln(os.Stderr, styleWarning.Render("⚠")+" "+styleWarning.Render(msg))
}

func Info(msg string) {
	fmt.Println(styleInfo.Render("ℹ") + " " + msg)
}

func Dim(msg string) {
	fmt.Println(styleDim.Render(msg))
}

func Header(title string) {
	fmt.Println()
	fmt.Println(styleBold.Underline(true).Render(title))
	fmt.Println()
}

// Table renders a table to stdout.
func Table(headers []string, rows [][]string) {
	t := table.NewWriter()
	t.SetOutputMirror(os.Stdout)
	t.SetStyle(table.StyleLight)
	t.Style().Options.SeparateRows = false

	// Header row
	headerRow := make(table.Row, len(headers))
	for i, h := range headers {
		headerRow[i] = text.Bold.Sprint(h)
	}
	t.AppendHeader(headerRow)

	// Data rows
	for _, row := range rows {
		r := make(table.Row, len(row))
		for i, cell := range row {
			if cell == "" {
				r[i] = styleDim.Render("—")
			} else {
				r[i] = cell
			}
		}
		t.AppendRow(r)
	}

	t.Render()
}

// KeyValue prints a two-column key-value list.
func KeyValue(pairs [][2]string) {
	maxLen := 0
	for _, p := range pairs {
		if len(p[0]) > maxLen {
			maxLen = len(p[0])
		}
	}
	for _, p := range pairs {
		key := p[0] + strings.Repeat(" ", maxLen-len(p[0])+1)
		val := p[1]
		if val == "" {
			val = styleDim.Render("—")
		}
		fmt.Printf("  %s  %s\n", styleBold.Render(key), val)
	}
}

// Fatal prints an error and exits 1.
func Fatal(msg string) {
	Error(msg)
	os.Exit(1)
}

// Fatalf prints a formatted error and exits 1.
func Fatalf(format string, args ...interface{}) {
	Fatal(fmt.Sprintf(format, args...))
}
