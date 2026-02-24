package cmd

import (
	"fmt"
	"net/http"

	"github.com/juhgiyo/loguetown/internal/server"
	"github.com/juhgiyo/loguetown/internal/tui"
	"github.com/spf13/cobra"
)

func newGuiCmd() *cobra.Command {
	var port int

	cmd := &cobra.Command{
		Use:   "gui",
		Short: "Launch the Loguetown web GUI",
		RunE: func(cmd *cobra.Command, args []string) error {
			projectPath := requireProject()

			srv, err := server.New(projectPath)
			if err != nil {
				return fmt.Errorf("init server: %w", err)
			}

			addr := fmt.Sprintf(":%d", port)
			tui.Success(fmt.Sprintf("Loguetown GUI running at http://localhost:%d", port))
			tui.Info("Press Ctrl+C to stop.")
			return http.ListenAndServe(addr, srv)
		},
	}

	cmd.Flags().IntVar(&port, "port", 4242, "Port to listen on")
	return cmd
}
