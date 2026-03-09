import { useNavigate } from "react-router-dom";
import { useTheme } from "next-themes";
import { useProjects } from "@/hooks/queries/use-projects";
import { useRunningSessions } from "@/hooks/queries/use-sessions";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from "@/components/ui/command";
import {
  LayoutDashboard,
  FolderKanban,
  Play,
  Sun,
  Moon,
  Monitor,
} from "lucide-react";

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function CommandPalette({
  open,
  onOpenChange,
}: CommandPaletteProps) {
  const navigate = useNavigate();
  const { setTheme } = useTheme();
  const projects = useProjects();
  const running = useRunningSessions();

  const projectList = projects.data ?? [];
  const runningSessions = running.data?.items ?? [];

  const go = (path: string) => {
    onOpenChange(false);
    navigate(path);
  };

  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} showCloseButton={false}>
      <CommandInput placeholder="Type a command or search..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>

        <CommandGroup heading="Navigation">
          <CommandItem onSelect={() => go("/")}>
            <LayoutDashboard />
            Dashboard
            <CommandShortcut>G D</CommandShortcut>
          </CommandItem>
          <CommandItem onSelect={() => go("/projects")}>
            <FolderKanban />
            Projects
            <CommandShortcut>G P</CommandShortcut>
          </CommandItem>
        </CommandGroup>

        {projectList.length > 0 && (
          <CommandGroup heading="Projects">
            {projectList.map((p) => (
              <CommandItem key={p.id} onSelect={() => go(`/projects/${p.id}`)}>
                <FolderKanban />
                {p.display_name}
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        {runningSessions.length > 0 && (
          <CommandGroup heading="Running Sessions">
            {runningSessions.map((s) => (
              <CommandItem
                key={s.run_id}
                onSelect={() =>
                  go(`/projects/${s.project_id}/sessions/${s.run_id}`)
                }
              >
                <Play />
                {s.role} ({s.run_id.slice(0, 8)})
              </CommandItem>
            ))}
          </CommandGroup>
        )}

        <CommandGroup heading="Theme">
          <CommandItem onSelect={() => { setTheme("light"); onOpenChange(false); }}>
            <Sun />
            Light
          </CommandItem>
          <CommandItem onSelect={() => { setTheme("dark"); onOpenChange(false); }}>
            <Moon />
            Dark
          </CommandItem>
          <CommandItem onSelect={() => { setTheme("system"); onOpenChange(false); }}>
            <Monitor />
            System
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
