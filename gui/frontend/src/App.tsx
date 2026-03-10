import { Routes, Route } from "react-router-dom";
import AppLayout from "./layouts/AppLayout";
import Dashboard from "./pages/Dashboard";
import ProjectList from "./pages/ProjectList";
import ProjectDetail from "./pages/ProjectDetail";
import SessionDetail from "./pages/SessionDetail";
import ResourceBrowser from "./pages/ResourceBrowser";
import ScheduledTasks from "./pages/ScheduledTasks";
import Settings from "./pages/Settings";
import NotFound from "./pages/NotFound";
import { useGlobalSSE } from "./hooks/useGlobalSSE";

export default function App() {
  useGlobalSSE();

  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Dashboard />} />
        <Route path="projects" element={<ProjectList />} />
        <Route path="projects/:projectId" element={<ProjectDetail />} />
        <Route
          path="projects/:projectId/sessions/:runId"
          element={<SessionDetail />}
        />
        <Route path="schedules" element={<ScheduledTasks />} />
        <Route
          path="resources/:resourceType"
          element={<ResourceBrowser />}
        />
        <Route path="settings" element={<Settings />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}
