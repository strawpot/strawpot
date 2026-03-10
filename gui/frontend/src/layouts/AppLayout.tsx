import { useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useTheme } from "next-themes";
import { LayoutDashboard, FolderKanban, Clock, Users, Wrench, Bot, Brain, Settings, Sun, Moon, Check, ChevronsUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useProject, useProjects } from "@/hooks/queries/use-projects";
import { useKeyboardShortcuts } from "@/hooks/useKeyboardShortcuts";
import CommandPalette from "@/components/CommandPalette";
import KeyboardShortcutsDialog from "@/components/KeyboardShortcutsDialog";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Separator } from "@/components/ui/separator";

const navItems = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/schedules", label: "Schedules", icon: Clock },
  { to: "/settings", label: "Settings", icon: Settings },
];

const resourceItems = [
  { to: "/resources/roles", label: "Roles", icon: Users },
  { to: "/resources/skills", label: "Skills", icon: Wrench },
  { to: "/resources/agents", label: "Agents", icon: Bot },
  { to: "/resources/memories", label: "Memory", icon: Brain },
];

function useBreadcrumbs() {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);

  const projectId = segments[0] === "projects" && segments[1] ? Number(segments[1]) : 0;
  const { data: project } = useProject(projectId, { enabled: projectId > 0 });

  const crumbs: { label: string; href?: string; projectSwitcher?: boolean }[] = [
    { label: "Dashboard", href: "/" },
  ];

  if (segments[0] === "projects") {
    crumbs.push({ label: "Projects", href: "/projects" });

    if (segments[1]) {
      const projectHref = `/projects/${segments[1]}`;
      const projectLabel = project?.display_name ?? `Project #${segments[1]}`;
      crumbs.push({ label: projectLabel, href: projectHref, projectSwitcher: true });

      if (segments[2] === "sessions" && segments[3]) {
        crumbs.push({ label: `Session ${segments[3].slice(0, 8)}…` });
      }
    }
  }

  if (segments[0] === "schedules") {
    crumbs.push({ label: "Scheduled Tasks" });
  }

  if (segments[0] === "settings") {
    crumbs.push({ label: "Settings" });
  }

  if (segments[0] === "resources") {
    const typeLabels: Record<string, string> = {
      roles: "Roles",
      skills: "Skills",
      agents: "Agents",
      memories: "Memory",
    };
    crumbs.push({ label: "Resources" });
    if (segments[1]) {
      crumbs[crumbs.length - 1].href = `/resources/${segments[1]}`;
      crumbs.push({ label: typeLabels[segments[1]] ?? segments[1] });
    }
  }

  return crumbs;
}

export default function AppLayout() {
  const crumbs = useBreadcrumbs();
  const navigate = useNavigate();
  const allProjects = useProjects();
  const { setTheme } = useTheme();
  const [cmdOpen, setCmdOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);

  useKeyboardShortcuts({
    onCommandPalette: () => setCmdOpen(true),
    onShortcutsHelp: () => setShortcutsOpen(true),
  });

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="flex w-56 flex-col border-r border-border bg-card">
        <div className="flex h-14 items-center border-b border-border px-4">
          <Link to="/" className="text-lg font-bold tracking-tight hover:text-foreground/80">StrawPot</Link>
        </div>
        <nav className="flex flex-col gap-1 p-3">
          {navItems.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}

          <div className="mt-4 mb-1 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
            Resources
          </div>
          {resourceItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground",
                )
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
        </nav>

      </aside>

      {/* Main content */}
      <div className="flex flex-1 flex-col">
        <header className="flex h-14 items-center justify-between border-b border-border px-6">
          <Breadcrumb>
            <BreadcrumbList>
              {crumbs.map((crumb, i) => {
                const isLast = i === crumbs.length - 1;
                return (
                  <BreadcrumbItem key={crumb.label}>
                    {i > 0 && <BreadcrumbSeparator />}
                    {crumb.projectSwitcher ? (
                      <DropdownMenu>
                        <DropdownMenuTrigger className="flex items-center gap-1 text-sm font-medium text-foreground hover:text-foreground/80 transition-colors">
                          {crumb.label}
                          <ChevronsUpDown className="h-3 w-3 text-muted-foreground" />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start">
                          {(allProjects.data ?? []).map((proj) => (
                            <DropdownMenuItem
                              key={proj.id}
                              onClick={() => navigate(`/projects/${proj.id}`)}
                            >
                              {crumb.href === `/projects/${proj.id}` ? (
                                <Check className="mr-2 h-3.5 w-3.5" />
                              ) : (
                                <span className="mr-2 inline-block w-3.5" />
                              )}
                              {proj.display_name}
                            </DropdownMenuItem>
                          ))}
                        </DropdownMenuContent>
                      </DropdownMenu>
                    ) : isLast ? (
                      <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                    ) : (
                      <BreadcrumbLink href={crumb.href}>
                        {crumb.label}
                      </BreadcrumbLink>
                    )}
                  </BreadcrumbItem>
                );
              })}
            </BreadcrumbList>
          </Breadcrumb>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCmdOpen(true)}
              className="flex items-center gap-1.5 rounded-md border border-border bg-muted/50 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted"
            >
              <kbd className="font-mono">⌘K</kbd>
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" className="h-8 w-8">
                  <Sun className="h-4 w-4 rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
                  <Moon className="absolute h-4 w-4 rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
                  <span className="sr-only">Toggle theme</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setTheme("light")}>
                  Light
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme("dark")}>
                  Dark
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setTheme("system")}>
                  System
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <Separator />
        <main className="flex-1 overflow-auto p-6">
          <Outlet />
        </main>
      </div>

      {/* Command palette + shortcuts help */}
      <CommandPalette open={cmdOpen} onOpenChange={setCmdOpen} />
      <KeyboardShortcutsDialog
        open={shortcutsOpen}
        onOpenChange={setShortcutsOpen}
      />
    </div>
  );
}
