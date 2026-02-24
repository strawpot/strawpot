package cmd

import (
	"bufio"
	"context"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/juhgiyo/loguetown/internal/config"
	"github.com/juhgiyo/loguetown/internal/conversation"
	"github.com/juhgiyo/loguetown/internal/embeddings"
	"github.com/juhgiyo/loguetown/internal/orchestrator"
	"github.com/juhgiyo/loguetown/internal/runner"
	"github.com/juhgiyo/loguetown/internal/scheduler"
	"github.com/juhgiyo/loguetown/internal/tui"
	"github.com/spf13/cobra"
)

func newChatCmd() *cobra.Command {
	var convID string

	cmd := &cobra.Command{
		Use:   "chat",
		Short: "Start an interactive session with the Loguetown orchestrator",
		Long: `lt chat opens a conversational session with the orchestrator agent.
You can describe objectives in natural language and the orchestrator will plan
and execute tasks using specialized AI agents.

Use --conv to resume an existing conversation by ID.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()

			cfg, err := config.LoadProject(projectPath)
			if err != nil {
				return fmt.Errorf("load project config: %w", err)
			}

			// Build embedding provider (best-effort).
			var embProvider embeddings.Provider
			if ep, e := embeddings.New(cfg.Embeddings); e == nil {
				embProvider = ep
			}

			// Build runner + scheduler.
			prov, err := runner.New(cfg.Runner)
			if err != nil {
				return fmt.Errorf("runner provider: %w", err)
			}
			r := &runner.Runner{
				ProjectPath:   projectPath,
				ProjectID:     cfg.Project.ID,
				ProjectName:   cfg.Project.Name,
				DefaultBranch: cfg.Project.DefaultBranch,
				EmbProvider:   embProvider,
				Provider:      prov,
				Cfg:           cfg.Runner,
				Checks:        cfg.Checks,
				PathRouting:   cfg.PathRouting,
			}
			sched := scheduler.New(r, cfg.Orchestrator)

			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()

			// Handle Ctrl+C gracefully.
			sigCh := make(chan os.Signal, 1)
			signal.Notify(sigCh, os.Interrupt, syscall.SIGTERM)
			go func() {
				<-sigCh
				fmt.Println("\nStopping scheduler…")
				sched.Stop()
				cancel()
			}()

			sched.Start(ctx)

			// Print prior conversation turns if resuming.
			if convID != "" {
				turns, err := conversation.ListTurns(convID)
				if err != nil {
					tui.Warning(fmt.Sprintf("Could not load conversation %s: %v", convID, err))
					convID = ""
				} else {
					fmt.Println()
					tui.Header(fmt.Sprintf("Resuming conversation %s", convID[:8]))
					for _, t := range turns {
						prefix := "You"
						if t.Role == "assistant" {
							prefix = "Orchestrator"
						}
						fmt.Printf("\033[1m%s:\033[0m %s\n\n", prefix, t.Content)
					}
				}
			}

			orchCfg := orchestrator.Config{
				APIKey:      cfg.Runner.APIKey,
				Model:       cfg.Runner.Model,
				ProjectID:   cfg.Project.ID,
				ProjectPath: projectPath,
				EmbProvider: embProvider,
				Enqueue:     sched.Enqueue,
			}

			tui.Info("Loguetown Orchestrator — type your objective or question. Ctrl+C to exit.")
			fmt.Println()

			scanner := bufio.NewScanner(os.Stdin)
			for {
				fmt.Print("\033[1mYou:\033[0m ")
				if !scanner.Scan() {
					break
				}
				line := strings.TrimSpace(scanner.Text())
				if line == "" {
					continue
				}
				if line == "exit" || line == "quit" {
					break
				}

				newConvID, reply, err := orchestrator.Chat(ctx, convID, line, orchCfg)
				if err != nil {
					tui.Warning(fmt.Sprintf("Error: %v", err))
					continue
				}
				convID = newConvID

				fmt.Printf("\n\033[1mOrchestrator:\033[0m %s\n\n", reply)
			}

			sched.Stop()
			if convID != "" {
				tui.Info(fmt.Sprintf("Conversation saved. Resume with: lt chat --conv %s", convID))
			}
			return nil
		},
	}

	cmd.Flags().StringVar(&convID, "conv", "", "Resume an existing conversation by ID")
	return cmd
}
