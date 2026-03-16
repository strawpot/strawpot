import { useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate } from "react-router-dom";
import { useTheme } from "next-themes";
import { ArrowLeft, LayoutDashboard, FolderKanban, Clock, CalendarClock, History, BotMessageSquare, Users, Wrench, Bot, Brain, Plug, Pencil, Plus, Settings, Sun, Moon, Check, ChevronsUpDown, Trash2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useProject, useProjects } from "@/hooks/queries/use-projects";
import { useImuConversations, useProjectConversations } from "@/hooks/queries/use-conversations";
import { useCreateConversation, useCreateImuConversation, useDeleteImuConversation, useDeleteConversation, useRenameConversation, useRenameImuConversation } from "@/hooks/mutations/use-conversations";
import type { ImuConversation } from "@/api/types";
import { Input } from "@/components/ui/input";
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
  { to: "/imu", label: "Bot Imu", icon: BotMessageSquare },
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/projects", label: "Projects", icon: FolderKanban },
  { to: "/settings", label: "Settings", icon: Settings },
];

const scheduleItems = [
  { to: "/schedules/runs", label: "Run History", icon: History },
  { to: "/schedules/recurring", label: "Recurring", icon: Clock },
  { to: "/schedules/one-time", label: "One-Time", icon: CalendarClock },
];

const resourceItems = [
  { to: "/resources/roles", label: "Roles", icon: Users },
  { to: "/resources/skills", label: "Skills", icon: Wrench },
  { to: "/resources/agents", label: "Agents", icon: Bot },
  { to: "/resources/memories", label: "Memory", icon: Brain },
  { to: "/integrations", label: "Integrations", icon: Plug },
];

interface ConvItem {
  id: number;
  title: string | null;
  session_count?: number;
}

function ConversationSidebarItem({
  conv,
  projectId,
  isActive,
  navigate,
}: {
  conv: ConvItem;
  projectId: number;
  isActive: boolean;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const [editing, setEditing] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const rename = useRenameConversation(projectId);
  const del = useDeleteConversation(projectId);

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setDraft(conv.title ?? "");
    setEditing(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const save = () => {
    const trimmed = draft.trim();
    rename.mutate({ conversationId: conv.id, title: trimmed || null });
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="px-1">
        <Input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); save(); }
            if (e.key === "Escape") { e.stopPropagation(); setEditing(false); }
          }}
          onClick={(e) => e.stopPropagation()}
          className="h-7 text-xs px-2"
        />
      </div>
    );
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        "flex items-center gap-1 rounded-md px-2 py-1.5 transition-colors",
        isActive
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground",
      )}
    >
      <button
        onClick={() => navigate(`/projects/${projectId}/conversations/${conv.id}`)}
        className="flex-1 min-w-0 text-left text-sm"
      >
        <span className="truncate block">{conv.title ?? `Conversation #${conv.id}`}</span>
      </button>
      {confirming ? (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); del.mutate(conv.id); setConfirming(false); }}
            className="text-xs text-destructive hover:text-destructive/80 font-medium"
            disabled={del.isPending}
          >
            Delete
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setConfirming(false); }}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            No
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-0.5 shrink-0" style={{ opacity: hovered ? 1 : 0 }}>
          <button
            onClick={startEdit}
            className="p-0.5 rounded text-muted-foreground hover:text-foreground transition-colors"
            title="Rename"
          >
            <Pencil className="h-3 w-3" />
          </button>
          {!isActive && (
            <button
              onClick={(e) => { e.stopPropagation(); setConfirming(true); }}
              className="p-0.5 rounded text-muted-foreground hover:text-destructive transition-colors"
              title="Delete"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ImuConversationSidebarItem({
  conv,
  isActive,
  navigate,
}: {
  conv: ImuConversation;
  isActive: boolean;
  navigate: ReturnType<typeof useNavigate>;
}) {
  const [editing, setEditing] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const rename = useRenameImuConversation();
  const del = useDeleteImuConversation();

  const startEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    setDraft(conv.title ?? "");
    setEditing(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const save = () => {
    const trimmed = draft.trim();
    rename.mutate({ conversationId: conv.id, title: trimmed || null });
    setEditing(false);
  };

  if (editing) {
    return (
      <div className="px-1">
        <Input
          ref={inputRef}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={save}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); save(); }
            if (e.key === "Escape") { e.stopPropagation(); setEditing(false); }
          }}
          onClick={(e) => e.stopPropagation()}
          className="h-7 text-xs px-2"
        />
      </div>
    );
  }

  return (
    <div
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      className={cn(
        "flex items-center gap-1 rounded-md px-2 py-1.5 transition-colors",
        isActive
          ? "bg-accent text-accent-foreground"
          : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground",
      )}
    >
      <button
        onClick={() => navigate(`/imu/${conv.id}`)}
        className="flex-1 min-w-0 text-left text-sm"
      >
        <span className="truncate block">{conv.title ?? `Conversation #${conv.id}`}</span>
      </button>
      {confirming ? (
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); del.mutate(conv.id); setConfirming(false); }}
            className="text-xs text-destructive hover:text-destructive/80 font-medium"
            disabled={del.isPending}
          >
            Delete
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); setConfirming(false); }}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            No
          </button>
        </div>
      ) : (
        <div className="flex items-center gap-0.5 shrink-0" style={{ opacity: hovered ? 1 : 0 }}>
          <button
            onClick={startEdit}
            className="p-0.5 rounded text-muted-foreground hover:text-foreground transition-colors"
            title="Rename"
          >
            <Pencil className="h-3 w-3" />
          </button>
          {!isActive && (
            <button
              onClick={(e) => { e.stopPropagation(); setConfirming(true); }}
              className="p-0.5 rounded text-muted-foreground hover:text-destructive transition-colors"
              title="Delete"
            >
              <Trash2 className="h-3 w-3" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ImuSidebar({ conversationId }: { conversationId: number }) {
  const navigate = useNavigate();
  const conversations = useImuConversations();
  const createConversation = useCreateImuConversation();

  return (
    <aside className="flex w-56 flex-col border-r border-border bg-card">
      <div className="flex h-14 items-center border-b border-border px-4">
        <Link to="/" className="text-lg font-bold tracking-tight hover:text-foreground/80">StrawPot</Link>
      </div>
      <div className="flex flex-col gap-1 p-3 flex-1 min-h-0">
        <button
          onClick={() => navigate("/imu")}
          className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          <BotMessageSquare className="h-4 w-4 shrink-0" />
          <span className="truncate">Bot Imu</span>
        </button>

        <div className="flex items-center justify-between px-3 pt-2 pb-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">Conversations</span>
          <button
            onClick={() => createConversation.mutate(undefined, {
              onSuccess: (conv) => navigate(`/imu/${conv.id}`),
            })}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="New conversation"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-0.5">
          {(conversations.data ?? []).map((conv) => (
            <ImuConversationSidebarItem
              key={conv.id}
              conv={conv}
              isActive={conv.id === conversationId}
              navigate={navigate}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}

function ConversationSidebar({ projectId, conversationId }: { projectId: number; conversationId: number }) {
  const navigate = useNavigate();
  const conversations = useProjectConversations(projectId, 1, 50);
  const createConversation = useCreateConversation();
  const project = useProject(projectId);

  return (
    <aside className="flex w-56 flex-col border-r border-border bg-card">
      <div className="flex h-14 items-center border-b border-border px-4">
        <Link to="/" className="text-lg font-bold tracking-tight hover:text-foreground/80">StrawPot</Link>
      </div>
      <div className="flex flex-col gap-1 p-3 flex-1 min-h-0">
        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          className="flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground transition-colors"
        >
          <ArrowLeft className="h-4 w-4 shrink-0" />
          <span className="truncate">{project.data?.display_name ?? "Back to Project"}</span>
        </button>

        <div className="flex items-center justify-between px-3 pt-2 pb-1">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">Conversations</span>
          <button
            onClick={() => createConversation.mutate(
              { project_id: projectId },
              { onSuccess: (conv) => navigate(`/projects/${projectId}/conversations/${conv.id}`) }
            )}
            className="text-muted-foreground hover:text-foreground transition-colors"
            title="New conversation"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto space-y-0.5">
          {(conversations.data?.items ?? []).map((conv) => (
            <ConversationSidebarItem
              key={conv.id}
              conv={conv}
              projectId={projectId}
              isActive={conv.id === conversationId}
              navigate={navigate}
            />
          ))}
        </div>
      </div>
    </aside>
  );
}

function useBreadcrumbs() {
  const location = useLocation();
  const segments = location.pathname.split("/").filter(Boolean);

  const projectId = segments[0] === "projects" && segments[1] ? Number(segments[1]) : 0;
  const conversationId = segments[2] === "conversations" && segments[3] ? Number(segments[3]) : 0;
  const { data: project } = useProject(projectId, { enabled: projectId > 0 });

  // Get conversation title from the sidebar list (already fetched by ConversationSidebar, so this is a cache hit)
  const { data: conversationsListData } = useProjectConversations(projectId, 1, 50);
  const conversationTitle = conversationsListData?.items.find((c) => c.id === conversationId)?.title ?? null;

  // Imu conversation title (cache hit from ImuSidebar)
  const imuConvId = segments[0] === "imu" && segments[1] ? Number(segments[1]) : 0;
  const { data: imuConversations } = useImuConversations();
  const imuConvTitle = imuConversations?.find((c) => c.id === imuConvId)?.title ?? null;

  const crumbs: { label: string; href?: string; projectSwitcher?: boolean }[] = [];

  if (segments[0] === "projects") {
    // Bot Imu (project_id=0) has its own section in the nav — show as "Bot Imu" not "Projects > Bot Imu"
    if (projectId === 0) {
      crumbs.push({ label: "Bot Imu", href: "/imu" });
      if (segments[2] === "sessions" && segments[3]) {
        crumbs.push({ label: `Session ${segments[3].slice(0, 8)}…` });
      }
    } else {
      crumbs.push({ label: "Projects", href: "/projects" });

      if (segments[1]) {
        const projectHref = `/projects/${segments[1]}`;
        const projectLabel = project?.display_name ?? `Project #${segments[1]}`;
        crumbs.push({ label: projectLabel, href: projectHref, projectSwitcher: true });

        if (segments[2] === "sessions" && segments[3]) {
          crumbs.push({ label: `Session ${segments[3].slice(0, 8)}…` });
        } else if (segments[2] === "conversations" && segments[3]) {
          crumbs.push({ label: conversationTitle ?? `Conversation #${segments[3]}` });
        }
      }
    }
  }

  if (segments[0] === "imu") {
    crumbs.push({ label: "Bot Imu", href: "/imu" });
    if (segments[1]) {
      crumbs.push({ label: imuConvTitle ?? `Conversation #${segments[1]}` });
    }
  }

  if (segments[0] === "schedules") {
    const scheduleLabels: Record<string, string> = {
      recurring: "Recurring Schedules",
      "one-time": "One-Time Schedules",
      runs: "Run History",
    };
    const sub = segments[1];
    if (sub && scheduleLabels[sub]) {
      crumbs.push({ label: "Schedules", href: "/schedules/recurring" });
      crumbs.push({ label: scheduleLabels[sub] });
    } else {
      crumbs.push({ label: "Schedules" });
    }
  }

  if (segments[0] === "settings") {
    crumbs.push({ label: "Settings" });
  }

  if (segments[0] === "integrations") {
    crumbs.push({ label: "Integrations" });
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
  const { data: imuConversations } = useImuConversations();
  const hasActiveImuSession = (imuConversations ?? []).some((c) => c.active_session_count > 0);
  const { setTheme } = useTheme();
  const [cmdOpen, setCmdOpen] = useState(false);
  const [shortcutsOpen, setShortcutsOpen] = useState(false);
  const convMatch = useMatch("/projects/:projectId/conversations/:conversationId");
  const convProjectId = convMatch ? Number(convMatch.params.projectId) : 0;
  const convId = convMatch ? Number(convMatch.params.conversationId) : 0;
  const imuMatch = useMatch("/imu/:conversationId");
  const imuConvId = imuMatch ? Number(imuMatch.params.conversationId) : 0;
  const imuSessionMatch = useMatch("/projects/0/sessions/:runId");

  useKeyboardShortcuts({
    onCommandPalette: () => setCmdOpen(true),
    onShortcutsHelp: () => setShortcutsOpen(true),
  });

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      {convMatch ? (
        <ConversationSidebar projectId={convProjectId} conversationId={convId} />
      ) : imuMatch ? (
        <ImuSidebar conversationId={imuConvId} />
      ) : (
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
                className={({ isActive }) => {
                  const active =
                    (isActive || (to === "/imu" && !!imuSessionMatch)) &&
                    !(to === "/projects" && !!imuSessionMatch);
                  return cn(
                    "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                    active
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:bg-accent/50 hover:text-accent-foreground",
                  );
                }}
              >
                <Icon className="h-4 w-4" />
                {label}
                {to === "/imu" && hasActiveImuSession && (
                  <span className="ml-auto h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                )}
              </NavLink>
            ))}

            <div className="mt-4 mb-1 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground/70">
              Schedules
            </div>
            {scheduleItems.map(({ to, label, icon: Icon }) => (
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
      )}

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
